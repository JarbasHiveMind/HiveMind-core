"""A peer can send a malformed wrapper frame.

HIVEMIND-MSG-1 §4: the payload of a QUERY, BROADCAST, PROPAGATE, ESCALATE or
CASCADE IS a nested ``HiveMessage``. A peer that nests a bus ``Message`` dict
(``{"type": ..., "data": ..., "context": ...}``) instead breaks the spec, and
``HiveMessage.payload`` raises ``TypeError`` when it tries to build the nested
envelope.

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


if __name__ == "__main__":
    unittest.main()
