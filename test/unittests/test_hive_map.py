"""Tests for PING/PONG network discovery: HiveMapper and protocol handlers."""
import time
import unittest
from unittest.mock import MagicMock, patch

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivemind_core.hive_map import HiveMapper, NodeInfo
from hivemind_core.protocol import HiveMindListenerProtocol


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pong(ping_id: str, peer: str, site_id: str = "",
               ping_ts: float = 1000.0, pong_ts: float = 1001.0,
               route: list = None) -> HiveMessage:
    """Build an inner PONG HiveMessage as the protocol would pass to HiveMapper."""
    pong = HiveMessage(
        HiveMessageType.PONG,
        payload={
            "ping_id": ping_id,
            "timestamp": ping_ts,
            "pong_timestamp": pong_ts,
            "peer": peer,
            "site_id": site_id,
        },
    )
    if route is not None:
        pong.replace_route(route)
    return pong


def _make_protocol() -> HiveMindListenerProtocol:
    """Build a minimal HiveMindListenerProtocol for testing."""
    agent = MagicMock()
    agent.bus = MagicMock()
    db = MagicMock()
    db.__enter__.return_value = db
    db.get_client_by_api_key.return_value = MagicMock()
    return HiveMindListenerProtocol(
        agent_protocol=agent,
        binary_data_protocol=MagicMock(),
        db=db,
    )


def _make_client(peer: str = "test-client::sess1",
                 can_propagate: bool = True) -> MagicMock:
    """Build a mock HiveMindClientConnection."""
    conn = MagicMock()
    conn.peer = peer
    conn.key = "test-key"
    conn.sess = MagicMock()
    conn.sess.session_id = "sess1"
    conn.sess.site_id = "test-site"
    conn.can_propagate = can_propagate
    conn.send = MagicMock()
    conn.disconnect = MagicMock()
    return conn


# ---------------------------------------------------------------------------
# HiveMapper tests
# ---------------------------------------------------------------------------

class TestNodeInfo(unittest.TestCase):
    def test_rtt_computed(self):
        node = NodeInfo(peer="a::1", ping_timestamp=1000.0, pong_timestamp=1000.5)
        self.assertAlmostEqual(node.rtt_ms, 500.0)

    def test_rtt_none_when_timestamps_missing(self):
        node = NodeInfo(peer="a::1")
        self.assertIsNone(node.rtt_ms)

    def test_rtt_none_when_one_missing(self):
        node = NodeInfo(peer="a::1", ping_timestamp=1000.0)
        self.assertIsNone(node.rtt_ms)


class TestHiveMapperOnPong(unittest.TestCase):
    def setUp(self):
        self.mapper = HiveMapper()
        self.ping_id = "abc-123"
        self.mapper.start_ping(self.ping_id)

    def test_accepts_valid_pong(self):
        pong = _make_pong(self.ping_id, "node-b::s1")
        result = self.mapper.on_pong(pong)
        self.assertTrue(result)
        self.assertIn("node-b::s1", self.mapper.nodes)

    def test_stores_site_id(self):
        pong = _make_pong(self.ping_id, "node-b::s1", site_id="bedroom")
        self.mapper.on_pong(pong)
        self.assertEqual(self.mapper.nodes["node-b::s1"].site_id, "bedroom")

    def test_deduplicates_pong_same_peer(self):
        pong1 = _make_pong(self.ping_id, "node-b::s1")
        pong2 = _make_pong(self.ping_id, "node-b::s1")
        self.assertTrue(self.mapper.on_pong(pong1))
        self.assertFalse(self.mapper.on_pong(pong2))
        # Only one node registered
        self.assertEqual(len(self.mapper.nodes), 1)

    def test_ignores_non_dict_payload(self):
        pong = HiveMessage(HiveMessageType.PONG, payload=None)
        result = self.mapper.on_pong(pong)
        self.assertFalse(result)

    def test_ignores_pong_with_no_peer(self):
        pong = HiveMessage(HiveMessageType.PONG, payload={"ping_id": self.ping_id})
        result = self.mapper.on_pong(pong)
        self.assertFalse(result)

    def test_builds_edges_from_route(self):
        route = [
            {"source": "node-b::s1", "targets": ["node-a::s0"]},
        ]
        pong = _make_pong(self.ping_id, "node-b::s1", route=route)
        self.mapper.on_pong(pong)
        self.assertIn("node-b::s1", self.mapper.edges)
        self.assertIn("node-a::s0", self.mapper.edges["node-b::s1"])

    def test_builds_deep_chain_edges(self):
        route = [
            {"source": "node-c::s2", "targets": ["node-b::s1"]},
            {"source": "node-b::s1", "targets": ["node-a::s0"]},
        ]
        pong = _make_pong(self.ping_id, "node-c::s2", route=route)
        self.mapper.on_pong(pong)
        self.assertIn("node-c::s2", self.mapper.edges)
        self.assertIn("node-b::s1", self.mapper.edges)

    def test_multiple_pongs_accumulate(self):
        pong_b = _make_pong(self.ping_id, "node-b::s1",
                            route=[{"source": "node-b::s1", "targets": ["node-a::s0"]}])
        pong_c = _make_pong(self.ping_id, "node-c::s2",
                            route=[
                                {"source": "node-c::s2", "targets": ["node-b::s1"]},
                                {"source": "node-b::s1", "targets": ["node-a::s0"]},
                            ])
        self.mapper.on_pong(pong_b)
        self.mapper.on_pong(pong_c)
        self.assertEqual(len(self.mapper.nodes), 2)
        self.assertIn("node-b::s1", self.mapper.nodes)
        self.assertIn("node-c::s2", self.mapper.nodes)


class TestHiveMapperToDict(unittest.TestCase):
    def test_empty_mapper(self):
        mapper = HiveMapper()
        result = mapper.to_dict()
        self.assertEqual(result["nodes"], [])
        self.assertEqual(result["edges"], [])

    def test_populated_mapper(self):
        mapper = HiveMapper()
        mapper.start_ping("p1")
        pong = _make_pong("p1", "node-b::s1", site_id="kitchen",
                          route=[{"source": "node-b::s1", "targets": ["node-a::s0"]}])
        mapper.on_pong(pong)
        result = mapper.to_dict()
        self.assertEqual(len(result["nodes"]), 1)
        self.assertEqual(result["nodes"][0]["peer"], "node-b::s1")
        self.assertEqual(result["nodes"][0]["site_id"], "kitchen")
        self.assertEqual(len(result["edges"]), 1)
        self.assertEqual(result["edges"][0]["source"], "node-b::s1")
        self.assertEqual(result["edges"][0]["target"], "node-a::s0")


class TestHiveMapperToJson(unittest.TestCase):
    def test_valid_json(self):
        import json
        mapper = HiveMapper()
        mapper.start_ping("p1")
        pong = _make_pong("p1", "node-b::s1")
        mapper.on_pong(pong)
        json_str = mapper.to_json()
        parsed = json.loads(json_str)
        self.assertIn("nodes", parsed)
        self.assertIn("edges", parsed)


class TestHiveMapperToAscii(unittest.TestCase):
    def test_empty_returns_no_nodes_message(self):
        mapper = HiveMapper()
        result = mapper.to_ascii()
        self.assertIn("No nodes", result)

    def test_single_hop(self):
        mapper = HiveMapper()
        mapper.start_ping("p1")
        pong = _make_pong("p1", "node-b::s1", site_id="bedroom",
                          route=[{"source": "node-b::s1", "targets": ["node-a::s0"]}])
        mapper.on_pong(pong)
        result = mapper.to_ascii(root_peer="node-a::s0")
        self.assertIn("node-b::s1", result)
        self.assertIn("bedroom", result)

    def test_root_labeled_self(self):
        mapper = HiveMapper()
        mapper.start_ping("p1")
        pong = _make_pong("p1", "node-b::s1",
                          route=[{"source": "node-b::s1", "targets": ["node-a::s0"]}])
        mapper.on_pong(pong)
        result = mapper.to_ascii(root_peer="node-a::s0")
        self.assertIn("[self]", result)
        self.assertIn("node-a::s0", result)


class TestHiveMapperClear(unittest.TestCase):
    def test_clear_resets_state(self):
        mapper = HiveMapper()
        mapper.start_ping("p1")
        pong = _make_pong("p1", "node-b::s1")
        mapper.on_pong(pong)
        mapper.clear()
        self.assertEqual(len(mapper.nodes), 0)
        self.assertEqual(len(mapper.edges), 0)
        self.assertEqual(len(mapper._seen_pongs), 0)


# ---------------------------------------------------------------------------
# Protocol handler tests
# ---------------------------------------------------------------------------

class TestHandlePingMessage(unittest.TestCase):
    def setUp(self):
        self.proto = _make_protocol()
        self.proto.peer = "master::sess0"
        self.proto.identity = MagicMock()
        self.proto.identity.site_id = "living-room"
        self.client = _make_client()

    def test_sends_pong_back_to_client(self):
        ping_inner = HiveMessage(HiveMessageType.PING, {
            "ping_id": "test-ping-1",
            "timestamp": 1000.0,
            "peer": "client::sess1",
            "site_id": "kitchen",
        })
        self.proto.handle_ping_message(ping_inner, self.client)
        self.assertTrue(self.client.send.called)

    def test_pong_wraps_in_propagate(self):
        ping_inner = HiveMessage(HiveMessageType.PING, {
            "ping_id": "test-ping-2",
            "timestamp": 1000.0,
            "peer": "client::sess1",
            "site_id": "kitchen",
        })
        self.proto.handle_ping_message(ping_inner, self.client)
        sent_msg = self.client.send.call_args[0][0]
        self.assertEqual(sent_msg.msg_type, HiveMessageType.PROPAGATE)
        inner = sent_msg.payload
        self.assertEqual(inner.msg_type, HiveMessageType.PONG)

    def test_pong_contains_correct_ping_id(self):
        ping_inner = HiveMessage(HiveMessageType.PING, {
            "ping_id": "my-unique-ping",
            "timestamp": 1000.0,
            "peer": "client::sess1",
            "site_id": "",
        })
        self.proto.handle_ping_message(ping_inner, self.client)
        sent_msg = self.client.send.call_args[0][0]
        pong_data = sent_msg.payload.payload
        self.assertEqual(pong_data["ping_id"], "my-unique-ping")

    def test_pong_carries_master_peer_and_site(self):
        ping_inner = HiveMessage(HiveMessageType.PING, {
            "ping_id": "p1",
            "timestamp": 1000.0,
            "peer": "client::sess1",
        })
        self.proto.handle_ping_message(ping_inner, self.client)
        sent_msg = self.client.send.call_args[0][0]
        pong_data = sent_msg.payload.payload
        self.assertEqual(pong_data["peer"], "master::sess0")
        self.assertEqual(pong_data["site_id"], "living-room")

    def test_emits_hive_ping_received_on_bus(self):
        ping_inner = HiveMessage(HiveMessageType.PING, {
            "ping_id": "p1",
            "timestamp": 1000.0,
            "peer": "client::sess1",
        })
        self.proto.handle_ping_message(ping_inner, self.client)
        bus = self.proto.agent_protocol.bus
        bus.emit.assert_called()
        call_args = bus.emit.call_args[0][0]
        self.assertEqual(call_args.msg_type, "hive.ping.received")

    def test_ignores_non_dict_payload(self):
        # Should not raise; should just log and return
        ping_inner = HiveMessage(HiveMessageType.PING, payload=None)
        ping_inner._payload = "not-a-dict"
        self.proto.handle_ping_message(ping_inner, self.client)
        self.assertFalse(self.client.send.called)


class TestHandlePongMessage(unittest.TestCase):
    def setUp(self):
        self.proto = _make_protocol()
        self.proto.peer = "master::sess0"
        self.proto.identity = MagicMock()
        self.proto.identity.site_id = "living-room"
        self.client = _make_client()

    def test_feeds_hive_mapper(self):
        pong_inner = _make_pong("p1", "node-b::s1", site_id="bedroom",
                                route=[{"source": "node-b::s1", "targets": ["master::sess0"]}])
        self.proto.hive_mapper.start_ping("p1")
        self.proto.handle_pong_message(pong_inner, self.client)
        self.assertIn("node-b::s1", self.proto.hive_mapper.nodes)

    def test_emits_hive_pong_received_on_bus(self):
        pong_inner = _make_pong("p1", "node-b::s1")
        self.proto.handle_pong_message(pong_inner, self.client)
        bus = self.proto.agent_protocol.bus
        bus.emit.assert_called()
        call_args = bus.emit.call_args[0][0]
        self.assertEqual(call_args.msg_type, "hive.pong.received")

    def test_ignores_non_dict_payload(self):
        pong_inner = HiveMessage(HiveMessageType.PONG, payload=None)
        pong_inner._payload = "not-a-dict"
        # Should not raise
        self.proto.handle_pong_message(pong_inner, self.client)


class TestPingPongViaPropagate(unittest.TestCase):
    """Verify that PING/PONG inner types are correctly dispatched from handle_propagate_message."""

    def setUp(self):
        self.proto = _make_protocol()
        self.proto.peer = "master::sess0"
        self.proto.identity = MagicMock()
        self.proto.identity.site_id = "living-room"
        self.client = _make_client()
        self.client.can_propagate = True

    def _make_propagate(self, inner: HiveMessage) -> HiveMessage:
        return HiveMessage(HiveMessageType.PROPAGATE, payload=inner)

    def test_propagate_with_ping_triggers_pong_send(self):
        ping_inner = HiveMessage(HiveMessageType.PING, {
            "ping_id": "pp-test-1",
            "timestamp": 1000.0,
            "peer": "client::sess1",
        })
        outer = self._make_propagate(ping_inner)
        with patch.object(self.proto.db, "get_client_by_api_key", return_value=MagicMock()):
            self.proto.handle_propagate_message(outer, self.client)
        self.assertTrue(self.client.send.called)
        # First call should be the PONG, others may be relay messages
        calls = self.client.send.call_args_list
        pong_calls = [c for c in calls
                      if c[0][0].msg_type == HiveMessageType.PROPAGATE
                      and c[0][0].payload.msg_type == HiveMessageType.PONG]
        self.assertEqual(len(pong_calls), 1)

    def test_propagate_with_pong_feeds_mapper(self):
        self.proto.hive_mapper.start_ping("pp-test-2")
        pong_inner = _make_pong("pp-test-2", "node-b::s1")
        outer = self._make_propagate(pong_inner)
        with patch.object(self.proto.db, "get_client_by_api_key", return_value=MagicMock()):
            self.proto.handle_propagate_message(outer, self.client)
        self.assertIn("node-b::s1", self.proto.hive_mapper.nodes)


if __name__ == "__main__":
    unittest.main()
