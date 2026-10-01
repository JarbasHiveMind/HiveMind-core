"""A frame the server cannot read is dropped, not answered with a closed
socket.

``HiveMindClientConnection.decode`` raised for a frame that is not a HiveMind
envelope at all. It now returns ``None``, which is the transport's existing
"keep receiving" signal.

This is a NARROWER door than the client receive doors in
hivemind-bus-client, which use ``HiveMessage.from_wire``, and the difference
is deliberate. A client has two answers to a bad frame, raise or drop, so its
one door refuses at the door. A server has a third: it answers the peer with
``hive.policy.denied`` / ``malformed_payload`` over the same connection. A
frame whose ENVELOPE reads but whose PAYLOAD is unusable must reach that
answer, so it is built here and not refused. Only a frame with no envelope is
dropped.

HIVEMIND-MSG-1 §3, quoted from architecture ``efc6566``: "A node **MUST**
forward or ignore a payload it does not understand. It **MUST NOT** reject
the connection over it, and it **MUST NOT** stop its own handler over it."
§6 repeats it in the MUST NOT list as "reject a connection over a payload it
does not understand (§3)".

Raising out of ``decode`` IS that rejection: the websocket transport catches
whatever ``decode`` raises and closes with 1008
(``hivemind_websocket_protocol._handle_inbound_message``), so one frame from a
remote peer dropped the session. ``decode`` therefore returns ``None`` for a
frame it cannot read. ``None`` is the transport's existing "keep receiving"
signal, already used for a buffered protocol-v3 Noise chunk and already
guarded there.

The four shapes below each raised out of ``decode`` before this change. They
are the shapes NOT covered by ``tests/test_malformed_wrapper_payload.py``,
which covers the frames that decode cleanly and then fail when the payload is
dereferenced.
"""
import unittest
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from hivemind_bus_client import HiveMessage, HiveMessageType
import hivemind_core.protocol as protocol_module
from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)

#: Frames that cannot be read at all, each with what makes it unreadable.
#: Every one of these raised out of ``decode`` and closed the connection.
UNREADABLE_FRAMES = {
    # no envelope: §2 requires msg_type + payload. The constructor raised
    # TypeError (missing positional argument 'msg_type')
    "no-msg_type": '{"payload":{}}',
    # not a JSON object: the constructor raised TypeError on ** of a list
    "frame-is-a-list": '[1,2]',
    "frame-is-a-number": '7',
    # a type outside the closed registry (§3): the HiveMessageType lookup
    # raised a bare ValueError
    "unknown-msg_type": '{"msg_type":"nope","payload":{}}',
    # not JSON at all: json.loads raised JSONDecodeError
    "not-json": 'not json at all',
}


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.callbacks = MagicMock()

    db_user = MagicMock()
    db_user.allowed_types = ["recognizer_loop:utterance"]
    db_user.is_admin = True

    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    return HiveMindListenerProtocol(agent_protocol=agent, db=db)


def _make_client(protocol, raw: str):
    """A client on an established protocol-v3 Noise session.

    A Noise session is the only way a non-HELLO/HANDSHAKE frame reaches
    ``decode``, so the transport is mocked to hand the plaintext straight to
    the payload door.
    """
    client = HiveMindClientConnection(
        key="test-key",
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=protocol,
        sess=Session("a-session"),
    )
    client.name = "test-client"
    client.allowed_types = ["recognizer_loop:utterance"]
    client.noise_transport = MagicMock()
    client.noise_transport.decrypt_frame.return_value = raw
    client.noise_transport.send_message.side_effect = (
        lambda payload, raw_send: raw_send(payload))
    return client


class TestAnUnreadableFrameIsDropped(unittest.TestCase):
    def test_every_unreadable_frame_returns_none_and_keeps_the_session(self):
        for label, raw in UNREADABLE_FRAMES.items():
            with self.subTest(frame=label):
                protocol = _make_protocol()
                client = _make_client(protocol, raw)

                message = client.decode(b"noise-frame")  # must not raise

                self.assertIsNone(message)
                # the §3 assertion: no close, and no recorded rejection
                client.disconnect.assert_not_called()

    def test_a_dropped_frame_does_not_log_the_frame(self):
        """A frame can carry a user's speech or a credential, so the log
        carries the exception class and the peer, never the frame."""
        protocol = _make_protocol()
        secret = "s3cr3t-in-the-frame"
        client = _make_client(protocol, '{"msg_type":"nope","payload":{"k":"%s"}}' % secret)

        # ``ovos_utils.log.LOG`` sets ``propagate = False`` on its logger, so
        # the module's LOG is patched rather than captured off the root.
        with patch.object(protocol_module, "LOG") as log:
            self.assertIsNone(client.decode(b"noise-frame"))

        joined = "\n".join(str(c) for c in log.warning.call_args_list)
        self.assertNotIn(secret, joined)
        self.assertIn("HIVEMIND-MSG-1", joined)


class TestTheDoorIsStillOpen(unittest.TestCase):
    """The controls: a readable frame is unaffected by the guard."""

    def test_a_well_formed_bus_frame_decodes(self):
        bus = Message("recognizer_loop:utterance", {"utterances": ["hi"]})
        raw = HiveMessage(HiveMessageType.BUS, bus).serialize()
        protocol = _make_protocol()
        client = _make_client(protocol, raw)

        message = client.decode(b"noise-frame")

        self.assertIsNotNone(message)
        self.assertEqual(message.msg_type, HiveMessageType.BUS)
        self.assertEqual(message.payload.msg_type, "recognizer_loop:utterance")

    def test_a_well_formed_wrapped_frame_keeps_its_inner_envelope(self):
        """§4: a node that admits the outer message MUST preserve the inner
        envelope unchanged. ``from_wire`` rebuilds it, so this asserts it."""
        bus = Message("recognizer_loop:utterance", {"utterances": ["hi"]})
        inner = HiveMessage(HiveMessageType.BUS, bus)
        raw = HiveMessage(HiveMessageType.PROPAGATE, inner).serialize()
        protocol = _make_protocol()
        client = _make_client(protocol, raw)

        message = client.decode(b"noise-frame")

        self.assertEqual(message.msg_type, HiveMessageType.PROPAGATE)
        self.assertEqual(message.payload.msg_type, HiveMessageType.BUS)
        self.assertEqual(message.payload.payload.msg_type,
                         "recognizer_loop:utterance")

    def test_the_door_keeps_the_per_hop_fields_the_frame_carries(self):
        """``source_peer`` and ``route`` survive the door. The routing code
        reads both, so a door that dropped them would change a delivery
        decision silently."""
        bus = Message("recognizer_loop:utterance", {"utterances": ["hi"]})
        raw = HiveMessage(HiveMessageType.BUS, bus,
                          source_peer="peer:1",
                          route=[{"source": "peer:1", "targets": []}]).serialize()
        protocol = _make_protocol()
        client = _make_client(protocol, raw)

        message = client.decode(b"noise-frame")

        self.assertEqual(message.source_peer, "peer:1")
        self.assertEqual(message.route, [{"source": "peer:1", "targets": []}])

    def test_a_payload_that_is_not_an_object_still_reaches_the_handler(self):
        """``from_wire`` refuses these two at the door. The server must not:
        the handler denies them and names the peer's bug, and that reply is
        the thing a door-side refusal would delete."""
        for raw in ('{"msg_type":"query","payload":[1,2]}',
                    '{"msg_type":"query","payload":7}'):
            with self.subTest(frame=raw):
                protocol = _make_protocol()
                client = _make_client(protocol, raw)

                message = client.decode(b"noise-frame")

                self.assertIsNotNone(message)
                protocol.handle_message(message, client)  # must not raise
                sent = "".join(str(c.args[0])
                               for c in client.send_msg.call_args_list)
                self.assertIn("malformed_payload", sent)
                client.disconnect.assert_not_called()

    def test_a_hello_without_a_payload_key_is_still_admitted(self):
        """§4 names HELLO as a type whose payload MAY be empty.
        ``from_wire`` refuses an ABSENT key for it. The server keeps its old
        answer, so this branch changes no HELLO behaviour."""
        protocol = _make_protocol()
        client = _make_client(protocol, '{"msg_type":"hello"}')

        message = client.decode(b"noise-frame")

        self.assertIsNotNone(message)
        self.assertEqual(message.msg_type, HiveMessageType.HELLO)

    def test_a_malformed_payload_still_reaches_the_handler_guard(self):
        """A frame whose ENVELOPE reads but whose PAYLOAD is unusable is NOT
        dropped here. It reaches the handler's `malformed_payload` denial,
        which tells the peer about its bug. Dropping it silently would lose
        that, so the two treatments must stay apart. This is the test that
        refuses `from_wire` at this site: `from_wire` refuses these frames,
        and refusing them here turns the denial into silence."""
        protocol = _make_protocol()
        client = _make_client(
            protocol, '{"msg_type":"propagate","payload":{"msg_type":"bus","payload":{}}}')

        message = client.decode(b"noise-frame")

        self.assertIsNotNone(message)
        protocol.handle_message(message, client)  # must not raise
        sent = "".join(str(c.args[0]) for c in client.send_msg.call_args_list)
        self.assertIn("malformed_payload", sent)
        client.disconnect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
