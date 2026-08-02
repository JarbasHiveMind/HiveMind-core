"""HIVEMIND-NODE-1 §3.3: a relay applies its own admission control to traffic
from its downstream nodes *before* forwarding it upstream.

Before this suite, ``handle_escalate_message``, ``handle_propagate_message`` and
``handle_cascade_message`` forwarded the payload upstream without ever running
``policy_chain``. A downstream client with an empty ``allowed_types`` could wrap
an arbitrary BUS message in an ESCALATE: the relay denied it locally, then
relayed it intact to the master, which admitted it against the *relay's*
credentials instead of the originator's.
"""
import unittest
from unittest.mock import MagicMock

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

from hivemind_core.policy import MessageTypeACLPolicy, PolicyChain
from hivemind_core.protocol import HiveMindClientConnection, HiveMindListenerProtocol

SITE = "test-site"


def _make_relay():
    """A relay node: an upstream master bound, a real ACL policy chain."""
    agent = MagicMock()
    bus = FakeBus()
    agent.bus = bus
    agent.get_bus.return_value = bus
    agent.answer_query.return_value = iter(())

    proto = HiveMindListenerProtocol.__new__(HiveMindListenerProtocol)
    proto.agent_protocol = agent
    proto.binary_data_protocol = MagicMock()
    proto.identity = MagicMock(public_key="relay-pubkey", site_id=SITE)
    proto.db = None
    proto.peer = "master:0.0.0.0"
    proto.clients = {}
    proto.hive_mapper = MagicMock()
    proto.illegal_callback = None
    proto.escalate_callback = None
    proto.propagate_callback = None
    proto.agent_bus_callback = None
    proto.cascade_select_callback = None
    proto.default_lang = "en-US"
    proto._seen_flood_ids = set()
    proto._pending_cascades = {}
    proto._upstream_hm = MagicMock()
    proto.policy_chain = PolicyChain(policies=[MessageTypeACLPolicy()])
    return proto, bus


def _make_client(allowed_types):
    client = MagicMock(spec=HiveMindClientConnection)
    client.allowed_types = list(allowed_types)
    client.is_admin = False
    client.peer = "downstream::1"
    client.can_escalate = True
    client.can_propagate = True
    client.sess = MagicMock()
    client.sess.session_id = "session-1"
    client.sess.serialize.return_value = {"session_id": "session-1"}
    client.sess.pipeline = None
    client.authorize.return_value = True
    client.send = MagicMock()
    return client


def _wrap(outer_type, bus_msg, target_site_id=None, metadata=None):
    inner = HiveMessage(HiveMessageType.BUS, payload=bus_msg)
    return HiveMessage(outer_type, payload=inner,
                       target_site_id=target_site_id, metadata=metadata)


def _speak():
    return Message("speak", {"utterance": "drop the shields"},
                   {"session": {"session_id": "session-1"}})


def _denials(client):
    return [c[0][0].payload for c in client.send.call_args_list
            if c[0][0].payload.msg_type == "hive.policy.denied"]


class TestRelayDeniesUnauthorizedUpstream(unittest.TestCase):
    """An unauthorized inner BUS message is not laundered upstream."""

    def _assert_denied(self, proto, client):
        proto._upstream_hm.emit.assert_not_called()
        denials = _denials(client)
        self.assertEqual(len(denials), 1)
        self.assertEqual(denials[0].data["denied_type"], "speak")
        self.assertEqual(denials[0].data["code"], "acl_disallowed_type")

    def test_escalate_with_empty_whitelist_is_not_forwarded(self):
        proto, _ = _make_relay()
        client = _make_client([])
        proto.handle_escalate_message(_wrap(HiveMessageType.ESCALATE, _speak()), client)
        self._assert_denied(proto, client)

    def test_propagate_with_empty_whitelist_is_not_forwarded(self):
        proto, _ = _make_relay()
        client = _make_client([])
        proto.handle_propagate_message(_wrap(HiveMessageType.PROPAGATE, _speak()), client)
        self._assert_denied(proto, client)

    def test_cascade_with_empty_whitelist_is_not_forwarded(self):
        proto, _ = _make_relay()
        client = _make_client([])
        proto.handle_cascade_message(
            _wrap(HiveMessageType.CASCADE, _speak(), metadata={"query_id": "q1"}),
            client)
        self._assert_denied(proto, client)

    def test_nested_escalate_wrapping_propagate_is_not_forwarded(self):
        """Nesting a routing envelope must not buy a way around the gate."""
        proto, _ = _make_relay()
        client = _make_client([])
        nested = HiveMessage(HiveMessageType.ESCALATE,
                             payload=_wrap(HiveMessageType.PROPAGATE, _speak()))
        proto.handle_escalate_message(nested, client)
        self._assert_denied(proto, client)


class TestRelayStillForwardsAuthorizedTraffic(unittest.TestCase):
    """Positive controls — the gate must not break relaying. These pass both
    before and after the fix."""

    def test_escalate_of_a_granted_type_is_forwarded(self):
        proto, _ = _make_relay()
        client = _make_client(["speak"])
        proto.handle_escalate_message(_wrap(HiveMessageType.ESCALATE, _speak()), client)
        proto._upstream_hm.emit.assert_called_once()
        self.assertEqual(_denials(client), [])

    def test_propagate_of_a_granted_type_is_forwarded(self):
        proto, _ = _make_relay()
        client = _make_client(["speak"])
        proto.handle_propagate_message(_wrap(HiveMessageType.PROPAGATE, _speak()), client)
        proto._upstream_hm.emit.assert_called_once()
        self.assertEqual(_denials(client), [])

    def test_ping_inside_a_propagate_is_forwarded_unreviewed(self):
        """A PING is mesh discovery, not agent traffic — no BUS payload to
        review, so the ACL whitelist does not apply to it."""
        proto, _ = _make_relay()
        client = _make_client([])
        ping = HiveMessage(HiveMessageType.PING, {"flood_id": "f1", "peer": client.peer})
        proto.handle_propagate_message(
            HiveMessage(HiveMessageType.PROPAGATE, payload=ping), client)
        self.assertTrue(proto._upstream_hm.emit.called)
        self.assertEqual(_denials(client), [])


class TestLocalDeliveryStillWorks(unittest.TestCase):
    """No regression on the site-targeted local-delivery path."""

    def test_site_targeted_escalate_reaches_the_agent_bus_once(self):
        proto, bus = _make_relay()
        client = _make_client(["speak"])
        emitted = []
        bus.on("speak", emitted.append)

        proto.handle_escalate_message(
            _wrap(HiveMessageType.ESCALATE, _speak(), target_site_id=SITE), client)

        self.assertEqual(len(emitted), 1)
        self.assertEqual(_denials(client), [])
        proto._upstream_hm.emit.assert_called_once()

    def test_denied_site_targeted_escalate_denies_exactly_once(self):
        """The relay gate and the local inject path must not both send a
        denial for the same message."""
        proto, bus = _make_relay()
        client = _make_client([])
        emitted = []
        bus.on("speak", emitted.append)

        proto.handle_escalate_message(
            _wrap(HiveMessageType.ESCALATE, _speak(), target_site_id=SITE), client)

        self.assertEqual(emitted, [])
        self.assertEqual(len(_denials(client)), 1)
        proto._upstream_hm.emit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
