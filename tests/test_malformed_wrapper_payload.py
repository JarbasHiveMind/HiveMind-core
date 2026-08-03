"""A peer can send a frame whose payload can not be reconstructed.

HIVEMIND-MSG-1 §4: the payload of a QUERY, BROADCAST, PROPAGATE, ESCALATE or
CASCADE IS a nested ``HiveMessage``, and the payload of a BUS or SHARED_BUS is
a bus ``Message``. ``HiveMessage.payload`` rebuilds those on access, and
rendering any message rebuilds it again through ``as_json``. Any payload of
the wrong shape makes one of them raise — ``TypeError`` for a bus ``Message``
dict where a nested envelope belongs, ``KeyError`` for a bus payload with no
``type``, ``AssertionError`` for a payload that is not a dict — so the node
catches ``Exception``, not one type.

That is the sender's bug, but a node must not raise out of its message
handler because a peer sent a bad frame. The node rejects the frame with the
same ``hive.policy.denied`` shape used for every other refused message, and
stays up.
"""
import unittest
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)

#: the shape a misbehaving peer sends: a bus Message dict, not a HiveMessage
BAD_PAYLOAD = {"type": "recognizer_loop:utterance",
               "data": {"utterances": ["hello"]},
               "context": {}}

WRAPPER_TYPES = [HiveMessageType.QUERY, HiveMessageType.BROADCAST,
                 HiveMessageType.PROPAGATE, HiveMessageType.ESCALATE,
                 HiveMessageType.CASCADE]


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.callbacks = MagicMock()

    db_user = MagicMock()
    db_user.allowed_types = ["recognizer_loop:utterance"]
    db_user.is_admin = True

    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    return HiveMindListenerProtocol(agent_protocol=agent, db=db,
                                    require_crypto=False,
                                    handshake_enabled=False)


def _make_client(protocol):
    client = HiveMindClientConnection(
        key="test-key",
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=protocol,
        sess=Session("a-session"),
    )
    client.name = "test-client"
    client.allowed_types = ["recognizer_loop:utterance"]
    client.crypto_key = None
    return client


def _sent(client):
    return "".join(str(c.args[0]) for c in client.send_msg.call_args_list)


class TestMalformedWrapperPayload(unittest.TestCase):
    def test_malformed_query_is_rejected_not_crashed(self):
        protocol = _make_protocol()
        client = _make_client(protocol)
        message = HiveMessage(HiveMessageType.QUERY, payload=BAD_PAYLOAD)

        protocol.handle_message(message, client)  # must not raise

        sent = _sent(client)
        self.assertIn("hive.policy.denied", sent)
        self.assertIn("malformed_payload", sent)

    def test_every_wrapper_type_rejects_a_malformed_payload(self):
        for msg_type in WRAPPER_TYPES:
            with self.subTest(msg_type=msg_type):
                protocol = _make_protocol()
                client = _make_client(protocol)
                message = HiveMessage(msg_type, payload=BAD_PAYLOAD)

                protocol.handle_message(message, client)  # must not raise

                self.assertIn("malformed_payload", _sent(client))

    def test_a_malformed_frame_does_not_kick_the_peer(self):
        """A bad frame is a bug in the peer, not an illegal action — the
        connection stays up so the peer can be told about it."""
        protocol = _make_protocol()
        client = _make_client(protocol)

        protocol.handle_message(
            HiveMessage(HiveMessageType.QUERY, payload=BAD_PAYLOAD), client)

        client.disconnect.assert_not_called()

    def test_a_well_formed_query_is_untouched(self):
        protocol = _make_protocol()
        client = _make_client(protocol)
        bus_msg = Message("recognizer_loop:utterance", {"utterances": ["hi"]})
        message = HiveMessage(HiveMessageType.QUERY,
                              payload=HiveMessage(HiveMessageType.BUS, bus_msg))

        protocol.handle_message(message, client)

        self.assertNotIn("malformed_payload", _sent(client))
        protocol.agent_protocol.get_bus.assert_called()


#: Exact frames an authenticated peer can put on the websocket. Each one used
#: to escape ``handle_message`` uncaught. Keyed by what makes them malformed.
MALFORMED_FRAMES = {
    # the nested envelope is rebuilt, and ITS payload is dereferenced too:
    # one forced level was not enough
    "propagate/nested-bus-without-type":
        '{"msg_type":"propagate","payload":{"msg_type":"bus","payload":{}}}',
    "escalate/nested-bus-without-type":
        '{"msg_type":"escalate","payload":{"msg_type":"bus","payload":{}}}',
    "query/nested-bus-without-type":
        '{"msg_type":"query","payload":{"msg_type":"bus","payload":{}}}',
    "cascade/nested-bus-without-type":
        '{"msg_type":"cascade","payload":{"msg_type":"bus","payload":{}}}',
    "broadcast/nested-bus-without-type":
        '{"msg_type":"broadcast","payload":{"msg_type":"bus","payload":{}}}',
    # a bus Message dict nested two levels down
    "propagate/bus-message-dict-two-levels-down":
        '{"msg_type":"propagate","payload":{"msg_type":"propagate",'
        '"payload":{"type":"x","data":{},"context":{}}}}',
    # SHARED_BUS rebuilds a bus Message from payload["type"] as well
    "shared_bus/payload-without-type":
        '{"msg_type":"shared_bus","payload":{}}',
    # a payload that is not a dict crashes the debug log, before any handler
    "query/payload-is-a-list": '{"msg_type":"query","payload":[1,2]}',
    "query/payload-is-a-number": '{"msg_type":"query","payload":7}',
}


class TestMalformedFrameOnTheWire(unittest.TestCase):
    """The frames above, through the real ``decode()`` and
    ``handle_message()`` path a websocket peer reaches."""

    def _handle(self, raw: str):
        protocol = _make_protocol()
        client = _make_client(protocol)
        message = client.decode(raw)  # must not raise
        protocol.handle_message(message, client)  # must not raise
        return client

    def test_every_malformed_frame_is_denied_and_the_peer_stays(self):
        for label, raw in MALFORMED_FRAMES.items():
            with self.subTest(frame=label):
                client = self._handle(raw)
                sent = _sent(client)
                self.assertIn("hive.policy.denied", sent)
                self.assertIn("malformed_payload", sent)
                client.disconnect.assert_not_called()

    def test_a_well_formed_frame_still_gets_through(self):
        raw = ('{"msg_type":"query","payload":{"msg_type":"bus","payload":'
               '{"type":"recognizer_loop:utterance",'
               '"data":{"utterances":["hi"]},"context":{}}}}')
        client = self._handle(raw)
        self.assertNotIn("malformed_payload", _sent(client))

    def test_a_well_formed_shared_bus_frame_still_gets_through(self):
        raw = ('{"msg_type":"shared_bus","payload":'
               '{"type":"recognizer_loop:utterance",'
               '"data":{"utterances":["hi"]},"context":{}}}')
        client = self._handle(raw)
        self.assertNotIn("malformed_payload", _sent(client))


class TestGuardRunsBeforeTheDebugLog(unittest.TestCase):
    """``handle_message`` logs the message before it dispatches it, and
    rendering a HiveMessage asserts the payload is a dict. The guard has to be
    above that line or a payload of ``7`` never reaches it."""

    def test_a_non_dict_payload_never_reaches_the_log(self):
        protocol = _make_protocol()
        client = _make_client(protocol)
        message = HiveMessage(HiveMessageType.QUERY, payload=7)

        protocol.handle_message(message, client)  # must not raise

        self.assertIn("malformed_payload", _sent(client))


if __name__ == "__main__":
    unittest.main()
