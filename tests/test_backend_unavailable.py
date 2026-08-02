"""The agent bus can be unreachable: ``get_bus`` raises ``ConnectionError``.

A message that the policy chain already admitted must never disappear in
silence — the originating peer gets an explicit ``backend_unavailable``
denial. Lifecycle handlers log and continue instead, so a dead OVOS bus
does not break connect/disconnect bookkeeping.
"""
import unittest
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.get_bus.side_effect = ConnectionError("no OVOS messagebus")
    agent.callbacks = MagicMock()

    db_user = MagicMock()
    db_user.allowed_types = ["recognizer_loop:utterance"]
    db_user.is_admin = False

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


def _sent_denials(client):
    return [c.args[0] for c in client.send_msg.call_args_list]


def _denial_codes(client):
    codes = []
    for raw in _sent_denials(client):
        if "hive.policy.denied" in str(raw):
            codes.append(raw)
    return codes


class TestBackendUnavailable(unittest.TestCase):
    def test_inject_tells_the_peer_the_backend_is_down(self):
        protocol = _make_protocol()
        client = _make_client(protocol)
        message = Message("recognizer_loop:utterance", {"utterances": ["hi"]},
                          {"session": {"session_id": "a-session"}})

        protocol.handle_inject_agent_msg(message, client)

        sent = "".join(str(c.args[0]) for c in client.send_msg.call_args_list)
        self.assertIn("hive.policy.denied", sent)
        self.assertIn("backend_unavailable", sent)

    def test_query_tells_the_peer_the_backend_is_down(self):
        protocol = _make_protocol()
        client = _make_client(protocol)
        bus_msg = Message("recognizer_loop:utterance", {"utterances": ["hi"]})
        message = HiveMessage(HiveMessageType.QUERY,
                              payload=HiveMessage(HiveMessageType.BUS, bus_msg))

        protocol.handle_query_message(message, client)

        sent = "".join(str(c.args[0]) for c in client.send_msg.call_args_list)
        self.assertIn("backend_unavailable", sent)

    def test_cascade_tells_the_peer_the_backend_is_down(self):
        protocol = _make_protocol()
        client = _make_client(protocol)
        bus_msg = Message("recognizer_loop:utterance", {"utterances": ["hi"]})
        message = HiveMessage(HiveMessageType.CASCADE,
                              payload=HiveMessage(HiveMessageType.BUS, bus_msg))

        protocol.handle_cascade_message(message, client)

        sent = "".join(str(c.args[0]) for c in client.send_msg.call_args_list)
        self.assertIn("backend_unavailable", sent)

    def test_disconnect_survives_a_dead_backend(self):
        protocol = _make_protocol()
        client = _make_client(protocol)

        protocol.handle_client_disconnected(client)  # must not raise

        client.disconnect.assert_called_once()

    def test_new_client_survives_a_dead_backend(self):
        protocol = _make_protocol()
        client = _make_client(protocol)

        protocol.handle_new_client(client)  # must not raise

        # the unreachable bus was tried, and the handler carried on
        protocol.agent_protocol.get_bus.assert_called_once_with(client)

    def test_invalid_key_survives_a_dead_backend(self):
        protocol = _make_protocol()
        client = _make_client(protocol)

        protocol.handle_invalid_key_connected(client)  # must not raise

    def test_invalid_protocol_survives_a_dead_backend(self):
        protocol = _make_protocol()
        client = _make_client(protocol)

        protocol.handle_invalid_protocol_version(client)  # must not raise


if __name__ == "__main__":
    unittest.main()
