"""A node answers a PING flood exactly once — HIVEMIND-NODE-1 §4.

A node that has an upstream runs two protocol objects at the same time: this
``HiveMindListenerProtocol``, serving its downstream clients, and a
``HiveMindSlaveProtocol`` (hivemind-bus-client) holding the connection to its
upstream. They are two halves of one node.

Each half used to keep its own ``flood_id`` cache and answer independently,
so one PING flood got two answers from one node — and the two answers carried
different identities, the slave's connection peer and the listener's public
key. Every relay therefore added a phantom node to the originator's hive map.

``bind_upstream`` is where the two halves are already wired together, so that
is where they are given one shared flood cache.
"""
from unittest.mock import MagicMock

from hivemind_bus_client.hive_map import FloodIdCache, HiveMapper
from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivemind_bus_client.protocol import HiveMindSlaveProtocol

from hivemind_core.protocol import HiveMindListenerProtocol

NODE_KEY = "-----BEGIN PUBLIC KEY-----NODE-A-----END PUBLIC KEY-----"


def _listener() -> HiveMindListenerProtocol:
    """A listener wired just enough to handle a PING."""
    node = object.__new__(HiveMindListenerProtocol)
    node.peer = "master:0.0.0.0"
    node.identity = MagicMock(public_key=NODE_KEY, site_id="site-a")
    node.clients = {}
    node.hive_mapper = HiveMapper()
    node.agent_protocol = MagicMock()
    node._seen_flood_ids = FloodIdCache()
    node._upstream_hm = None
    return node


def _slave() -> HiveMindSlaveProtocol:
    """A slave protocol wired just enough to handle a PING."""
    slave = object.__new__(HiveMindSlaveProtocol)
    slave.hm = MagicMock(session_id="sess-1")
    slave.identity = MagicMock(public_key=NODE_KEY, site_id="site-a")
    slave.identity.name = "node-a"
    slave.site_id = "site-a"
    slave.hive_mapper = HiveMapper()
    slave.cascade_aggregator = None
    slave._emit = MagicMock()
    return slave


def _ping(flood_id: str) -> HiveMessage:
    return HiveMessage(HiveMessageType.PING,
                       {"flood_id": flood_id, "peer": "origin",
                        "site_id": "site-z", "timestamp": 1.0})


def _client() -> MagicMock:
    client = MagicMock()
    client.peer = "satellite::1"
    return client


class TestBindUpstreamSharesTheFloodCache:
    def test_slave_gets_the_listener_cache(self):
        node, slave = _listener(), _slave()
        node.bind_upstream(slave)
        assert slave.hive_mapper._seen_flood_ids is node._seen_flood_ids, (
            "the two halves of one node must share one flood cache")

    def test_listener_suppressed_after_the_slave_answered(self):
        """The upstream half saw the flood first; the listener must stay quiet.

        This is the real relay path: the flood arrives from upstream, the
        slave answers it, then the downstream answers come back through the
        listener carrying the same flood_id.
        """
        node, slave = _listener(), _slave()
        node.bind_upstream(slave)
        conn = MagicMock()
        node.clients = {"satellite::1": conn}

        slave.handle_ping(_ping("f1"))
        assert slave._emit.call_count == 1, "the node must answer once"

        node.handle_ping_message(_ping("f1"), _client())

        assert conn.send.call_count == 0, (
            "this node already took part in flood f1 through its upstream "
            "half; answering again maps one node as two (NODE-1 §4)")

    def test_slave_suppressed_after_the_listener_answered(self):
        """Same rule in the other direction: a downstream-originated flood."""
        node, slave = _listener(), _slave()
        node.bind_upstream(slave)

        node.handle_ping_message(_ping("f1"), _client())
        slave.handle_ping(_ping("f1"))

        assert slave._emit.call_count == 0, (
            "the listener half already answered flood f1 for this node")

    def test_flood_is_still_recorded_once_shared(self):
        node, slave = _listener(), _slave()
        node.bind_upstream(slave)
        slave.handle_ping(_ping("f1"))
        assert "f1" in node._seen_flood_ids


class TestNodeWithoutUpstreamStillAnswers:
    def test_answers_a_new_flood_exactly_once(self):
        """No upstream, no shared cache — the node must still answer once."""
        node = _listener()
        conn = MagicMock()
        node.clients = {"satellite::1": conn}

        node.handle_ping_message(_ping("f1"), _client())
        assert conn.send.call_count == 1, "a top-level master must answer"

        node.handle_ping_message(_ping("f1"), _client())
        assert conn.send.call_count == 1, "and must not answer twice"

    def test_malformed_ping_without_flood_id_is_never_answered(self):
        node = _listener()
        conn = MagicMock()
        node.clients = {"satellite::1": conn}
        node.handle_ping_message(_ping(""), _client())
        assert conn.send.call_count == 0


class TestResponsivePingIdentity:
    def test_listener_ping_carries_the_stable_public_key(self):
        """The slave half announces ``public_key``; the listener half must too.

        Without it a consumer has no stable identity for a master-only node
        and cannot tell that two ``peer`` labels belong to one node.
        """
        node = _listener()
        conn = MagicMock()
        node.clients = {"satellite::1": conn}

        node.handle_ping_message(_ping("f1"), _client())

        payload = conn.send.call_args[0][0].payload.payload
        assert payload["public_key"] == NODE_KEY
        assert payload["peer"] == NODE_KEY
        assert payload["flood_id"] == "f1"

    def test_both_halves_announce_the_same_public_key(self):
        """One node, one identity — whichever half happens to answer."""
        node, slave = _listener(), _slave()
        conn = MagicMock()
        node.clients = {"satellite::1": conn}

        node.handle_ping_message(_ping("f1"), _client())
        slave.handle_ping(_ping("f2"))

        listener_payload = conn.send.call_args[0][0].payload.payload
        slave_payload = slave._emit.call_args[0][0].payload.payload
        assert listener_payload["public_key"] == slave_payload["public_key"]

    def test_flood_cache_is_bounded(self):
        """Long-running nodes must not grow the cache without limit."""
        node = _listener()
        for i in range(1100):
            node.handle_ping_message(_ping(f"f{i}"), _client())
        assert len(node._seen_flood_ids) <= 1000
