"""A frame that cannot be read as a HiveMessage is handled by stage.

On an established session the frame is dropped and the connection stays up
(HIVEMIND-MSG-1 §3): one bad frame must not take a satellite off the mesh. A
malformed HELLO or HANDSHAKE, and any unreadable frame before the Noise
session exists, closes the connection with 1008 and is recorded in
``recent_rejections`` (HIVEMIND-MSG-1 §4).

The established-session cases run through the websocket transport's own
receive path, because that is where a raise out of ``decode`` turns into a
closed socket.
"""
import json
import unittest
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_websocket_protocol import HiveMindTornadoWebSocket

import hivemind_core.protocol as protocol_module
from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)

UTTERANCE = "recognizer_loop:utterance"

#: frames an authenticated peer can put on an established session that are
#: not readable as a HiveMessage
UNREADABLE_FRAMES = {
    "not-json": "not json at all",
    "frame-is-a-list": "[1, 2]",
    "frame-is-a-number": "7",
    "no-msg_type": '{"payload": {}}',
    "unknown-msg_type": '{"msg_type": "nope", "payload": {}}',
    "bus-payload-is-a-string": '{"msg_type": "bus", "payload": "a string"}',
    "unexpected-envelope-key": '{"msg_type": "bus", "bogus": 1, "payload": {}}',
    "binary-garbage": b"\xff" * 10,
}

#: HELLO and HANDSHAKE frames whose payload is not a JSON object
MALFORMED_HANDSHAKE_FRAMES = {
    f"{msg_type}/{label}": json.dumps(frame)
    for msg_type in ("hello", "shake")
    for label, frame in {
        "payload-is-a-json-string": {
            "msg_type": msg_type, "payload": json.dumps({"site_id": "injected"})},
        "payload-is-null": {"msg_type": msg_type, "payload": None},
        "payload-is-a-list": {"msg_type": msg_type, "payload": [1, 2]},
        "payload-is-a-number": {"msg_type": msg_type, "payload": 7},
        "payload-key-absent": {"msg_type": msg_type},
    }.items()
}


def _bus_frame(text: str) -> str:
    message = Message(UTTERANCE, {"utterances": [text]},
                      {"session": Session("a-session").serialize()})
    return HiveMessage(HiveMessageType.BUS, message).serialize()


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.get_bus.return_value = agent.bus
    agent.callbacks = MagicMock()

    db_user = MagicMock()
    db_user.allowed_types = [UTTERANCE]
    db_user.is_admin = True

    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    return HiveMindListenerProtocol(agent_protocol=agent, db=db)


def _make_client(protocol, established: bool):
    client = HiveMindClientConnection(
        key="test-key",
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=protocol,
        sess=Session("a-session"),
    )
    client.name = "test-client"
    client.allowed_types = [UTTERANCE]
    if established:
        # the Noise transport hands the plaintext it is given straight to the
        # payload door, as an authenticated frame would arrive
        client.noise_transport = MagicMock()
        client.noise_transport.send_message.side_effect = (
            lambda payload, raw_send: raw_send(payload))
    return client


def _make_socket(protocol, client):
    socket = HiveMindTornadoWebSocket.__new__(HiveMindTornadoWebSocket)
    socket.hm_protocol = protocol
    socket.client = client
    socket.source_ip = None
    socket.close = MagicMock()
    return socket


def _receive(socket, plaintext):
    socket.client.noise_transport.decrypt_frame.return_value = plaintext
    socket._handle_inbound_message(b"noise-frame")


def _injected_utterances(protocol):
    return [c.args[0] for c in protocol.agent_protocol.bus.emit.call_args_list
            if getattr(c.args[0], "msg_type", None) == UTTERANCE]


class TestEstablishedSessionDropsTheFrame(unittest.TestCase):
    def test_an_unreadable_frame_leaves_the_connection_open(self):
        for label, frame in UNREADABLE_FRAMES.items():
            with self.subTest(frame=label):
                protocol = _make_protocol()
                client = _make_client(protocol, established=True)
                socket = _make_socket(protocol, client)

                _receive(socket, frame)

                socket.close.assert_not_called()
                client.disconnect.assert_not_called()
                self.assertEqual(protocol.get_recent_rejections(), [])

    def test_the_next_valid_bus_message_is_still_handled(self):
        for label, frame in UNREADABLE_FRAMES.items():
            with self.subTest(frame=label):
                protocol = _make_protocol()
                client = _make_client(protocol, established=True)
                socket = _make_socket(protocol, client)

                _receive(socket, frame)
                _receive(socket, _bus_frame("still here"))

                socket.close.assert_not_called()
                injected = _injected_utterances(protocol)
                self.assertEqual(len(injected), 1)
                self.assertEqual(injected[0].data["utterances"], ["still here"])

    def test_a_body_that_is_not_utf8_is_dropped(self):
        protocol = _make_protocol()
        client = _make_client(protocol, established=True)
        client.noise_transport.decrypt_frame.side_effect = UnicodeDecodeError(
            "utf-8", b"\xff", 0, 1, "invalid start byte")

        self.assertIsNone(client.decode(b"noise-frame"))
        client.disconnect.assert_not_called()

    def test_a_dropped_frame_is_not_logged(self):
        secret = "s3cr3t-in-the-frame"
        protocol = _make_protocol()
        client = _make_client(protocol, established=True)
        client.noise_transport.decrypt_frame.return_value = (
            '{"msg_type": "nope", "payload": {"k": "%s"}}' % secret)

        with patch.object(protocol_module, "LOG") as log:
            self.assertIsNone(client.decode(b"noise-frame"))

        logged = "\n".join(str(c) for c in log.method_calls)
        self.assertIn("dropping malformed wire frame", logged)
        self.assertNotIn(secret, logged)

    def test_a_readable_frame_with_an_unusable_payload_is_still_answered(self):
        protocol = _make_protocol()
        client = _make_client(protocol, established=True)
        socket = _make_socket(protocol, client)

        _receive(socket, '{"msg_type": "query", "payload": [1, 2]}')

        sent = "".join(str(c.args[0]) for c in client.send_msg.call_args_list)
        self.assertIn("malformed_payload", sent)
        socket.close.assert_not_called()


class TestMalformedHandshakeCloses(unittest.TestCase):
    def assertClosed(self, protocol, client):
        client.disconnect.assert_called_once()
        self.assertEqual(client.disconnect.call_args.args[0], 1008)
        rejections = protocol.get_recent_rejections()
        self.assertEqual(len(rejections), 1)
        self.assertEqual(rejections[0]["code"], 1008)
        self.assertEqual(rejections[0]["reason"], "malformed_frame")

    def test_before_the_session_a_malformed_hello_or_handshake_closes(self):
        for label, frame in MALFORMED_HANDSHAKE_FRAMES.items():
            with self.subTest(frame=label):
                protocol = _make_protocol()
                client = _make_client(protocol, established=False)

                with self.assertRaises(ValueError):
                    client.decode(frame)

                self.assertClosed(protocol, client)
                self.assertEqual(client.site_id, "unknown")

    def test_the_encrypted_hello_that_completes_the_session_closes_too(self):
        # the peer's own HELLO is the first message over the Noise transport
        for label, frame in MALFORMED_HANDSHAKE_FRAMES.items():
            with self.subTest(frame=label):
                protocol = _make_protocol()
                client = _make_client(protocol, established=True)
                client.noise_transport.decrypt_frame.return_value = frame

                with self.assertRaises(ValueError):
                    client.decode(b"noise-frame")

                self.assertClosed(protocol, client)

    def test_before_the_session_any_unreadable_frame_closes(self):
        for label, frame in UNREADABLE_FRAMES.items():
            with self.subTest(frame=label):
                protocol = _make_protocol()
                client = _make_client(protocol, established=False)

                with self.assertRaises(ValueError):
                    client.decode(frame)

                self.assertClosed(protocol, client)

    def test_a_well_formed_hello_and_handshake_still_decode(self):
        for frame in ('{"msg_type": "hello", "payload": {}}',
                      '{"msg_type": "shake", "payload": {"noise": {}}}'):
            with self.subTest(frame=frame):
                protocol = _make_protocol()
                client = _make_client(protocol, established=False)

                message = client.decode(frame)

                self.assertIsInstance(message.payload, dict)
                client.disconnect.assert_not_called()
                self.assertEqual(protocol.get_recent_rejections(), [])


if __name__ == "__main__":
    unittest.main()
