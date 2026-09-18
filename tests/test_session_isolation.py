"""Session isolation between peers.

Covers two related defects:

* the reserved ``"default"`` session must never reach the OVOS bus on behalf
  of an unauthorized peer (HIVEMIND-BRIDGE-1 §4.1, OVOS-SESSION-2 §5);
* ``peer`` must be unique per connection so two clients can not collide and
  cross-deliver each other's responses (HIVEMIND-BRIDGE-1 §3,
  HIVEMIND-AGENT-1 §3).
"""
import unittest
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.get_bus.return_value = agent.bus
    agent.callbacks = MagicMock()

    db_user = MagicMock()
    db_user.allowed_types = ["recognizer_loop:utterance"]
    db_user.is_admin = False

    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    return HiveMindListenerProtocol(agent_protocol=agent, db=db)


def _drop_configured_policies(protocol):
    """Keep only the built-in, non-removable policies.

    Models an operator running a non-OVOS backend: everything the operator
    listed in ``policy.chain`` (OVOSAgentPolicy included) is gone.
    """
    import hivemind_core.policy as builtins
    keep = [p for p in protocol.policy_chain.policies
            if type(p).__module__ == builtins.__name__]
    protocol.policy_chain.policies = keep
    protocol.policy_chain._optional = [False] * len(keep)


def _make_client(protocol, sess, key="test-key", name="test-client"):
    client = HiveMindClientConnection(
        key=key,
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=protocol,
        sess=sess,
    )
    client.name = name
    client.allowed_types = ["recognizer_loop:utterance"]
    return client


class TestReservedDefaultSession(unittest.TestCase):
    def test_new_connection_never_stays_in_the_reserved_session(self):
        # the websocket plugin mints every connection with
        # Session(session_id="default"); core must move it off the reserved
        # id before anything can be emitted under it.
        protocol = _make_protocol()
        client = _make_client(protocol, Session(session_id="default"))

        protocol.handle_new_client(client)

        self.assertNotEqual(client.sess.session_id, "default")

    def test_disconnect_does_not_leak_a_default_session_of_a_non_admin(self):
        protocol = _make_protocol()
        client = _make_client(protocol, Session(session_id="default"))
        client.is_admin = False

        protocol.handle_client_disconnected(client)

        emitted = protocol.agent_protocol.bus.emit.call_args[0][0]
        self.assertEqual(emitted.msg_type, "hive.client.disconnect")
        session_id = emitted.context["session"]["session_id"]
        self.assertNotEqual(session_id, "default")
        self.assertTrue(session_id.endswith(":default"))

    def test_disconnect_keeps_the_session_of_an_admin(self):
        protocol = _make_protocol()
        client = _make_client(protocol, Session(session_id="default"))
        client.is_admin = True

        protocol.handle_client_disconnected(client)

        emitted = protocol.agent_protocol.bus.emit.call_args[0][0]
        self.assertEqual(emitted.context["session"]["session_id"], "default")

    def test_core_policy_chain_denies_a_non_admin_default_session(self):
        # the gate must live in core, next to the force-prepended
        # MessageTypeACLPolicy, not only in the removable OVOSAgentPolicy.
        protocol = _make_protocol()
        _drop_configured_policies(protocol)
        client = _make_client(protocol, Session(session_id="a-session"))
        client.is_admin = False
        message = Message("recognizer_loop:utterance", {"utterances": ["hi"]},
                          {"session": {"session_id": "default"}})

        verdict = protocol.policy_chain.review(message, client)

        self.assertTrue(verdict.denied)
        self.assertEqual(verdict.code, "session_id_default_forbidden")

    def test_core_policy_chain_allows_an_admin_default_session(self):
        protocol = _make_protocol()
        _drop_configured_policies(protocol)
        client = _make_client(protocol, Session(session_id="a-session"))
        client.is_admin = True
        message = Message("recognizer_loop:utterance", {"utterances": ["hi"]},
                          {"session": {"session_id": "default"}})

        verdict = protocol.policy_chain.review(message, client)

        self.assertFalse(verdict.denied)


class TestPeerUniqueness(unittest.TestCase):
    def _hello(self, protocol, client, session_id):
        from hivemind_bus_client import HiveMessage, HiveMessageType
        payload = {"session": Session(session_id).serialize()}
        protocol.handle_hello_message(
            HiveMessage(HiveMessageType.HELLO, payload), client)

    def test_two_connections_with_the_same_name_and_session_do_not_collide(self):
        protocol = _make_protocol()
        first = _make_client(protocol, Session("conn-1"))
        second = _make_client(protocol, Session("conn-2"))

        self._hello(protocol, first, "shared-session")
        self._hello(protocol, second, "shared-session")

        self.assertNotEqual(first.peer, second.peer)
        self.assertEqual(len(protocol.clients), 2)
        self.assertIs(protocol.clients[first.peer], first)
        self.assertIs(protocol.clients[second.peer], second)

    def test_a_client_can_hello_twice_without_being_renamed(self):
        protocol = _make_protocol()
        client = _make_client(protocol, Session("conn-1"))

        self._hello(protocol, client, "my-session")
        peer = client.peer
        self._hello(protocol, client, "my-session")

        self.assertEqual(client.peer, peer)
        self.assertEqual(list(protocol.clients), [peer])


if __name__ == "__main__":
    unittest.main()
