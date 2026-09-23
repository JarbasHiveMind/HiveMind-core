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

from hivemind_core.protocol import (HiveMindClientConnection,
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
                self.assertEqual(entry["code"], 1008)
                self.assertEqual(entry["peer"], client.peer)
                self.assertEqual(set(entry), {"time", "peer", "code", "reason"})

    def test_every_kick_closes_with_the_policy_code(self):
        for handler, msg_type, _ in CASES:
            with self.subTest(handler=handler):
                proto = _make_protocol()
                client = _make_client(proto)
                getattr(proto, handler)(_wrap(msg_type), client)
                code, text = client.disconnect.call_args[0]
                self.assertEqual(code, 1008)
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


if __name__ == "__main__":
    unittest.main()
