"""The five origination-permission kicks are recorded for the operator.

HIVEMIND-NODE-1 §4 lets a node "treat a violation as misbehaviour and close
the connection instead of returning a denial". The client that is kicked is
already admitted, so the only record of the kick is the node's own
``recent_rejections`` ring. Before this test the five handlers closed the
connection with no ring entry and no close code, and the operator saw a
normal close.
"""
import unittest
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import (POLICY_KICK_CLOSE_CODE,
                                    HiveMindClientConnection,
                                    HiveMindListenerProtocol)


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.callbacks = MagicMock()
    return HiveMindListenerProtocol(agent_protocol=agent, db=MagicMock())


def _make_client(protocol, **flags):
    client = HiveMindClientConnection(
        key="secret-access-key", send_msg=MagicMock(), disconnect=MagicMock(),
        hm_protocol=protocol)
    client.name = "evil-client"
    client.is_admin = flags.get("is_admin", False)
    client.can_broadcast = flags.get("can_broadcast", False)
    client.can_propagate = flags.get("can_propagate", False)
    client.can_escalate = flags.get("can_escalate", False)
    return client


def _wrap(outer_type):
    inner = HiveMessage(HiveMessageType.BUS,
                        payload=Message("speak", {"utterance": "hi"}))
    return HiveMessage(outer_type, payload=inner)


CASES = [
    ("handle_broadcast_message", HiveMessageType.BROADCAST, "illegal_broadcast"),
    ("handle_propagate_message", HiveMessageType.PROPAGATE, "illegal_propagate"),
    ("handle_query_message", HiveMessageType.QUERY, "illegal_query"),
    ("handle_cascade_message", HiveMessageType.CASCADE, "illegal_cascade"),
    ("handle_escalate_message", HiveMessageType.ESCALATE, "illegal_escalate"),
]


class TestPermissionKicksRecorded(unittest.TestCase):

    def test_every_kick_records_its_reason(self):
        for handler, msg_type, reason in CASES:
            with self.subTest(handler=handler):
                proto = _make_protocol()
                client = _make_client(proto)
                getattr(proto, handler)(_wrap(msg_type), client)
                entries = proto.get_recent_rejections()
                self.assertEqual(len(entries), 1)
                entry = entries[0]
                self.assertEqual(entry["reason"], reason)
                self.assertEqual(entry["code"], POLICY_KICK_CLOSE_CODE)
                self.assertEqual(entry["peer"], client.peer)
                self.assertEqual(set(entry), {"time", "peer", "code", "reason"})

    def test_every_kick_closes_with_the_policy_code(self):
        for handler, msg_type, _ in CASES:
            with self.subTest(handler=handler):
                proto = _make_protocol()
                client = _make_client(proto)
                getattr(proto, handler)(_wrap(msg_type), client)
                code, text = client.disconnect.call_args[0]
                self.assertEqual(code, POLICY_KICK_CLOSE_CODE)
                self.assertNotEqual(code, 1008)
                self.assertNotIn(client.key, text)

    def test_reasons_are_registered(self):
        for _, _, reason in CASES:
            self.assertIn(reason, HiveMindListenerProtocol.REJECTION_REASONS)

    def test_permitted_client_is_not_recorded(self):
        # control: the same five messages from a client that may send them
        for handler, msg_type, _ in CASES:
            with self.subTest(handler=handler):
                proto = _make_protocol()
                client = _make_client(proto, is_admin=True, can_broadcast=True,
                                      can_propagate=True, can_escalate=True)
                try:
                    getattr(proto, handler)(_wrap(msg_type), client)
                except Exception:
                    pass  # routing/forwarding is out of scope here
                self.assertEqual(proto.get_recent_rejections(), [])
                client.disconnect.assert_not_called()


class TestKickCloseCodeIsNotAnIdentityRefusal(unittest.TestCase):
    """1008 is the fleet client's "your credentials are refused"."""

    def test_the_policy_code_is_in_the_private_use_range(self):
        # RFC 6455 section 7.4.2: 4000-4999 is for private use. The HIVEMIND
        # specifications name no close code at all, so the kick takes one
        # from that range and nothing else can claim it.
        self.assertGreaterEqual(POLICY_KICK_CLOSE_CODE, 4000)
        self.assertLessEqual(POLICY_KICK_CLOSE_CODE, 4999)

    def test_the_policy_code_is_not_the_identity_refusal_code(self):
        self.assertNotEqual(POLICY_KICK_CLOSE_CODE, 1008)


class TestKickSurvivesATransportWithoutCloseCodes(unittest.TestCase):
    """hivemind-email builds the connection with ``def _disconnect() -> None``."""

    def _client_with_codeless_disconnect(self, proto):
        calls = []

        def _disconnect():
            calls.append(())

        client = HiveMindClientConnection(
            key="secret-access-key", send_msg=MagicMock(),
            disconnect=_disconnect, hm_protocol=proto)
        client.is_admin = False
        client.can_broadcast = False
        client.can_propagate = False
        client.can_escalate = False
        return client, calls

    def test_every_kick_still_disconnects(self):
        for handler, msg_type, reason in CASES:
            with self.subTest(handler=handler):
                proto = _make_protocol()
                client, calls = self._client_with_codeless_disconnect(proto)
                getattr(proto, handler)(_wrap(msg_type), client)
                self.assertEqual(calls, [()], "the client was never kicked")
                entries = proto.get_recent_rejections()
                self.assertEqual([e["reason"] for e in entries], [reason])

    def test_the_dispatcher_safety_net_also_survives_it(self):
        # the net closes with 1011 on a handler that raised; on this
        # transport the coded close used to raise inside the net itself
        proto = _make_protocol()
        client, calls = self._client_with_codeless_disconnect(proto)
        message = _wrap(HiveMessageType.BROADCAST)
        client.is_admin = True
        client.can_broadcast = True
        proto.handle_broadcast_message = MagicMock(side_effect=RuntimeError("boom"))
        proto.handle_message(message, client)
        self.assertEqual(calls, [()])

    def test_a_transport_that_takes_a_code_still_gets_one(self):
        # control: the coded call is not lost for every transport
        proto = _make_protocol()
        client = _make_client(proto)
        proto.handle_broadcast_message(_wrap(HiveMessageType.BROADCAST), client)
        client.disconnect.assert_called_once_with(
            POLICY_KICK_CLOSE_CODE, "BROADCAST is not allowed for this client")

    def test_a_transport_error_is_not_read_as_a_missing_code(self):
        # a TypeError raised INSIDE the transport must not be swallowed as
        # "this disconnect takes no code"
        proto = _make_protocol()

        def _disconnect(code=1000, reason=""):
            raise TypeError("the transport itself failed")

        client = HiveMindClientConnection(
            key="k", send_msg=MagicMock(), disconnect=_disconnect,
            hm_protocol=proto)
        client.is_admin = False
        client.can_broadcast = False
        with self.assertRaises(TypeError):
            proto.handle_broadcast_message(_wrap(HiveMessageType.BROADCAST),
                                           client)


class TestAKickIsRecordedBesideAnEarlierRejection(unittest.TestCase):

    def test_an_earlier_record_does_not_swallow_the_kick(self):
        proto = _make_protocol()
        client = _make_client(proto)
        proto.record_rejection(client, 1011, "internal_error")
        proto.handle_broadcast_message(_wrap(HiveMessageType.BROADCAST), client)
        reasons = [e["reason"] for e in proto.get_recent_rejections()]
        self.assertIn("illegal_broadcast", reasons)
        self.assertIn("internal_error", reasons)

    def test_one_connection_repeating_one_violation_is_recorded_once(self):
        proto = _make_protocol()
        client = _make_client(proto)
        for _ in range(5):
            proto.handle_broadcast_message(_wrap(HiveMessageType.BROADCAST),
                                           client)
        reasons = [e["reason"] for e in proto.get_recent_rejections()]
        self.assertEqual(reasons, ["illegal_broadcast"])


class TestKicksDoNotEvictAdmissionRejections(unittest.TestCase):

    def test_a_hundred_kicks_leave_the_invalid_key_entry(self):
        proto = _make_protocol()
        admission = _make_client(proto)
        proto.record_rejection(admission, 1008, "invalid_key")
        for _ in range(proto.kick_history_size):
            kicked = _make_client(proto)
            proto.handle_broadcast_message(_wrap(HiveMessageType.BROADCAST),
                                           kicked)
        reasons = [e["reason"] for e in proto.get_recent_rejections()]
        self.assertIn("invalid_key", reasons)
        self.assertEqual(reasons.count("illegal_broadcast"),
                         proto.kick_history_size)

    def test_the_kick_ring_is_still_bounded(self):
        proto = _make_protocol()
        for _ in range(proto.kick_history_size + 10):
            kicked = _make_client(proto)
            proto.handle_broadcast_message(_wrap(HiveMessageType.BROADCAST),
                                           kicked)
        self.assertEqual(len(proto.recent_kicks), proto.kick_history_size)


if __name__ == "__main__":
    unittest.main()
