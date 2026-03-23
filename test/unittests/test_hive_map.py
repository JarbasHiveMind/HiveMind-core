"""Tests for PING-only network discovery: HiveMapper and protocol handlers."""
import time
import unittest
from unittest.mock import MagicMock, patch

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivemind_bus_client.hive_map import HiveMapper, NodeInfo
from hivemind_core.protocol import HiveMindListenerProtocol


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ping(flood_id: str, peer: str, site_id: str = "",
               timestamp: float = 1000.0,
               route: list = None) -> HiveMessage:
    """Build an inner PING HiveMessage as the protocol would pass to HiveMapper."""
    ping = HiveMessage(
        HiveMessageType.PING,
        payload={
            "flood_id": flood_id,
            "timestamp": timestamp,
            "peer": peer,
            "site_id": site_id,
        },
    )
    if route is not None:
        ping.replace_route(route)
    return ping


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
    def test_latency_computed(self):
        node = NodeInfo(peer="a::1", timestamp=1000.0, received_at=1000.5)
        self.assertAlmostEqual(node.latency_ms, 500.0)

    def test_latency_none_when_timestamps_missing(self):
        node = NodeInfo(peer="a::1")
        self.assertIsNone(node.latency_ms)

    def test_latency_none_when_one_missing(self):
        node = NodeInfo(peer="a::1", timestamp=1000.0)
        self.assertIsNone(node.latency_ms)


class TestHiveMapperOnPing(unittest.TestCase):
    def setUp(self):
        self.mapper = HiveMapper()
        self.flood_id = "abc-123"
        self.mapper.start_ping(self.flood_id)

    def test_accepts_valid_ping(self):
        ping = _make_ping(self.flood_id, "node-b::s1")
        result = self.mapper.on_ping(ping)
        self.assertTrue(result)
        self.assertIn("node-b::s1", self.mapper.nodes)

    def test_stores_site_id(self):
        ping = _make_ping(self.flood_id, "node-b::s1", site_id="bedroom")
        self.mapper.on_ping(ping)
        self.assertEqual(self.mapper.nodes["node-b::s1"].site_id, "bedroom")

    def test_deduplicates_ping_same_peer(self):
        ping1 = _make_ping(self.flood_id, "node-b::s1")
        ping2 = _make_ping(self.flood_id, "node-b::s1")
        self.assertTrue(self.mapper.on_ping(ping1))
        self.assertFalse(self.mapper.on_ping(ping2))
        # Only one node registered
        self.assertEqual(len(self.mapper.nodes), 1)

    def test_ignores_non_dict_payload(self):
        ping = HiveMessage(HiveMessageType.PING, payload=None)
        result = self.mapper.on_ping(ping)
        self.assertFalse(result)

    def test_ignores_ping_with_no_peer(self):
        ping = HiveMessage(HiveMessageType.PING, payload={"flood_id": self.flood_id})
        result = self.mapper.on_ping(ping)
        self.assertFalse(result)

    def test_builds_edges_from_route(self):
        route = [
            {"source": "node-b::s1", "targets": ["node-a::s0"]},
        ]
        ping = _make_ping(self.flood_id, "node-b::s1", route=route)
        self.mapper.on_ping(ping)
        self.assertIn("node-b::s1", self.mapper.edges)
        self.assertIn("node-a::s0", self.mapper.edges["node-b::s1"])

    def test_builds_deep_chain_edges(self):
        route = [
            {"source": "node-c::s2", "targets": ["node-b::s1"]},
            {"source": "node-b::s1", "targets": ["node-a::s0"]},
        ]
        ping = _make_ping(self.flood_id, "node-c::s2", route=route)
        self.mapper.on_ping(ping)
        self.assertIn("node-c::s2", self.mapper.edges)
        self.assertIn("node-b::s1", self.mapper.edges)

    def test_multiple_pings_accumulate(self):
        ping_b = _make_ping(self.flood_id, "node-b::s1",
                            route=[{"source": "node-b::s1", "targets": ["node-a::s0"]}])
        ping_c = _make_ping(self.flood_id, "node-c::s2",
                            route=[
                                {"source": "node-c::s2", "targets": ["node-b::s1"]},
                                {"source": "node-b::s1", "targets": ["node-a::s0"]},
                            ])
        self.mapper.on_ping(ping_b)
        self.mapper.on_ping(ping_c)
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
        ping = _make_ping("p1", "node-b::s1", site_id="kitchen",
                          route=[{"source": "node-b::s1", "targets": ["node-a::s0"]}])
        mapper.on_ping(ping)
        result = mapper.to_dict()
        self.assertEqual(len(result["nodes"]), 1)
        self.assertEqual(result["nodes"][0]["peer"], "node-b::s1")
        self.assertEqual(result["nodes"][0]["site_id"], "kitchen")
        self.assertIn("timestamp", result["nodes"][0])
        self.assertEqual(len(result["edges"]), 1)
        self.assertEqual(result["edges"][0]["source"], "node-b::s1")
        self.assertEqual(result["edges"][0]["target"], "node-a::s0")


class TestHiveMapperToJson(unittest.TestCase):
    def test_valid_json(self):
        import json
        mapper = HiveMapper()
        mapper.start_ping("p1")
        ping = _make_ping("p1", "node-b::s1")
        mapper.on_ping(ping)
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
        ping = _make_ping("p1", "node-b::s1", site_id="bedroom",
                          route=[{"source": "node-b::s1", "targets": ["node-a::s0"]}])
        mapper.on_ping(ping)
        result = mapper.to_ascii(root_peer="node-a::s0")
        self.assertIn("node-b::s1", result)
        self.assertIn("bedroom", result)

    def test_root_labeled_self(self):
        mapper = HiveMapper()
        mapper.start_ping("p1")
        ping = _make_ping("p1", "node-b::s1",
                          route=[{"source": "node-b::s1", "targets": ["node-a::s0"]}])
        mapper.on_ping(ping)
        result = mapper.to_ascii(root_peer="node-a::s0")
        self.assertIn("[self]", result)
        self.assertIn("node-a::s0", result)


class TestHiveMapperClear(unittest.TestCase):
    def test_clear_resets_state(self):
        mapper = HiveMapper()
        mapper.start_ping("p1")
        ping = _make_ping("p1", "node-b::s1")
        mapper.on_ping(ping)
        mapper.clear()
        self.assertEqual(len(mapper.nodes), 0)
        self.assertEqual(len(mapper.edges), 0)
        self.assertEqual(len(mapper._seen_pings), 0)


# ---------------------------------------------------------------------------
# Protocol handler tests
# ---------------------------------------------------------------------------

class TestHandlePingMessage(unittest.TestCase):
    def setUp(self):
        self.proto = _make_protocol()
        self.proto.peer = "master::sess0"
        self.proto.identity = MagicMock()
        self.proto.identity.site_id = "living-room"
        self.proto.identity.public_key = "test-pubkey"
        self.proto.identity.lang = "en-us"
        self.client = _make_client()

    def test_feeds_hive_mapper(self):
        ping_inner = HiveMessage(HiveMessageType.PING, {
            "flood_id": "test-ping-1",
            "timestamp": 1000.0,
            "peer": "client::sess1",
            "site_id": "kitchen",
        })
        self.proto.handle_ping_message(ping_inner, self.client)
        self.assertIn("client::sess1", self.proto.hive_mapper.nodes)

    def test_emits_hive_ping_received_on_bus(self):
        ping_inner = HiveMessage(HiveMessageType.PING, {
            "flood_id": "p1",
            "timestamp": 1000.0,
            "peer": "client::sess1",
        })
        self.proto.handle_ping_message(ping_inner, self.client)
        bus = self.proto.agent_protocol.bus
        bus.emit.assert_called()
        call_args = bus.emit.call_args[0][0]
        self.assertEqual(call_args.msg_type, "hive.ping.received")

    def test_bus_event_contains_flood_id(self):
        ping_inner = HiveMessage(HiveMessageType.PING, {
            "flood_id": "my-flood-123",
            "timestamp": 1000.0,
            "peer": "client::sess1",
        })
        self.proto.handle_ping_message(ping_inner, self.client)
        bus = self.proto.agent_protocol.bus
        call_args = bus.emit.call_args[0][0]
        self.assertIn("flood_id", call_args.data)
        self.assertEqual(call_args.data["flood_id"], "my-flood-123")

    def test_new_flood_id_sends_responsive_ping(self):
        # Register client in proto.clients so it receives the flood
        self.proto.clients[self.client.peer] = self.client
        ping_inner = HiveMessage(HiveMessageType.PING, {
            "flood_id": "new-flood-1",
            "timestamp": 1000.0,
            "peer": "client::sess1",
            "site_id": "kitchen",
        })
        self.proto.handle_ping_message(ping_inner, self.client)
        self.assertTrue(self.client.send.called)
        sent_msg = self.client.send.call_args[0][0]
        self.assertEqual(sent_msg.msg_type, HiveMessageType.PROPAGATE)
        inner = sent_msg.payload
        self.assertEqual(inner.msg_type, HiveMessageType.PING)

    def test_responsive_ping_carries_master_peer_and_site(self):
        self.proto.clients[self.client.peer] = self.client
        ping_inner = HiveMessage(HiveMessageType.PING, {
            "flood_id": "p1",
            "timestamp": 1000.0,
            "peer": "client::sess1",
        })
        self.proto.handle_ping_message(ping_inner, self.client)
        sent_msg = self.client.send.call_args[0][0]
        ping_data = sent_msg.payload.payload
        self.assertEqual(ping_data["peer"], "master::sess0")
        self.assertEqual(ping_data["site_id"], "living-room")
        self.assertEqual(ping_data["flood_id"], "p1")

    def test_responsive_ping_includes_public_key_and_lang(self):
        """Responsive PING must announce this node's public_key and lang."""
        self.proto.clients[self.client.peer] = self.client
        ping_inner = HiveMessage(HiveMessageType.PING, {
            "flood_id": "pk-test",
            "timestamp": 1000.0,
            "peer": "client::sess1",
        })
        self.proto.handle_ping_message(ping_inner, self.client)
        sent_msg = self.client.send.call_args[0][0]
        ping_data = sent_msg.payload.payload
        self.assertEqual(ping_data["public_key"], "test-pubkey")
        self.assertEqual(ping_data["lang"], "en-us")

    def test_duplicate_flood_id_does_not_resend(self):
        # Pre-register the flood_id in HiveMapper so it counts as already seen
        self.proto.hive_mapper.check_flood_id("already-seen")
        ping_inner = HiveMessage(HiveMessageType.PING, {
            "flood_id": "already-seen",
            "timestamp": 1000.0,
            "peer": "client::sess1",
            "site_id": "kitchen",
        })
        self.proto.handle_ping_message(ping_inner, self.client)
        self.assertFalse(self.client.send.called)

    def test_ignores_non_dict_payload(self):
        # Should not raise; should just log and return
        ping_inner = HiveMessage(HiveMessageType.PING, payload=None)
        ping_inner._payload = "not-a-dict"
        self.proto.handle_ping_message(ping_inner, self.client)
        self.assertFalse(self.client.send.called)


class TestPingViaPropagate(unittest.TestCase):
    """Verify that PING inner type is correctly dispatched from handle_propagate_message."""

    def setUp(self):
        self.proto = _make_protocol()
        self.proto.peer = "master::sess0"
        self.proto.identity = MagicMock()
        self.proto.identity.site_id = "living-room"
        self.proto.identity.public_key = "test-pubkey"
        self.proto.identity.lang = "en-us"
        self.client = _make_client()
        self.client.can_propagate = True

    def _make_propagate(self, inner: HiveMessage) -> HiveMessage:
        return HiveMessage(HiveMessageType.PROPAGATE, payload=inner)

    def test_propagate_with_ping_sends_responsive_ping(self):
        # Client must be in proto.clients to receive the flood
        self.proto.clients[self.client.peer] = self.client
        ping_inner = HiveMessage(HiveMessageType.PING, {
            "flood_id": "pp-test-1",
            "timestamp": 1000.0,
            "peer": "client::sess1",
        })
        outer = self._make_propagate(ping_inner)
        with patch.object(self.proto.db, "get_client_by_api_key", return_value=MagicMock()):
            self.proto.handle_propagate_message(outer, self.client)
        self.assertTrue(self.client.send.called)
        calls = self.client.send.call_args_list
        ping_calls = [c for c in calls
                      if c[0][0].msg_type == HiveMessageType.PROPAGATE
                      and c[0][0].payload.msg_type == HiveMessageType.PING]
        self.assertGreaterEqual(len(ping_calls), 1)


if __name__ == "__main__":
    unittest.main()
