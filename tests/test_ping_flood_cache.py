"""The PING flood_id cache: FIFO eviction, sized for the client count.

A dedup miss is not a dropped message — it makes the node answer a flood it
has already answered, which is a whole extra fan-out across the mesh. The
cache is therefore load-bearing for the scale fix, and two properties matter:

* eviction drops the **oldest** flood_id. The previous ``set.pop()`` dropped an
  arbitrary one, so a flood_id registered a moment ago could go while a stale
  one stayed.
* the cap grows with the number of connected clients. Every client can start a
  flood of its own, so a fixed 1000 thrashes exactly on the meshes that can
  least afford the extra floods.
"""
import uuid
from unittest.mock import MagicMock

from hivemind_bus_client.hive_map import FloodIdCache, HiveMapper
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindListenerProtocol


def _make_node(num_clients: int) -> HiveMindListenerProtocol:
    """A listener with *num_clients* connected peers, built without the
    dataclass __post_init__ (no config, no database, no agent connection)."""
    node = object.__new__(HiveMindListenerProtocol)
    node.peer = "master:0.0.0.0"
    node.identity = MagicMock(public_key="node-pubkey", site_id=None)
    node.clients = {f"peer{i}": MagicMock() for i in range(num_clients)}
    node.hive_mapper = HiveMapper()
    node.agent_protocol = MagicMock()
    node._upstream_hm = None
    node._seen_flood_ids = FloodIdCache()
    node._answered_floods = FloodIdCache()
    node._last_ping_flood = 0.0
    # The throttle is disabled here on purpose. This module is about the
    # flood_id cache, and the throttle runs *before* the _seen_flood_ids
    # claim (see handle_ping_message), so a non-zero interval would throttle
    # every flood after the first and the cache would stay almost empty —
    # the tests below would then be measuring the limiter, not eviction.
    node.ping_flood_interval = 0.0
    return node


def _ping(flood_id: str, peer: str = "sat") -> HiveMessage:
    return HiveMessage(HiveMessageType.PING, {
        "flood_id": flood_id,
        "peer": peer,
        "site_id": None,
        "timestamp": 0.0,
    })


def _feed(node, flood_ids):
    client = next(iter(node.clients.values()))
    for i, fid in enumerate(flood_ids):
        node.handle_ping_message(_ping(fid, peer=f"sat{i}"), client)


def test_burst_larger_than_the_old_fixed_cap_still_dedups():
    """20 clients size the cache at 2000, so a 1500-flood burst evicts nothing.

    The same burst against the old fixed 1000-entry set had already dropped a
    third of it, and every dropped id buys a duplicate flood.
    """
    node = _make_node(num_clients=20)
    flood_ids = [str(uuid.uuid4()) for _ in range(1500)]
    _feed(node, flood_ids)

    assert len(node._seen_flood_ids) == 1500
    assert all(fid in node._seen_flood_ids for fid in flood_ids)


def test_eviction_is_oldest_first():
    """Past the cap, the ids that go are the ones registered first."""
    node = _make_node(num_clients=1)  # floor of 1000 applies
    flood_ids = [str(uuid.uuid4()) for _ in range(1010)]
    _feed(node, flood_ids)

    assert len(node._seen_flood_ids) == 1000
    assert not any(fid in node._seen_flood_ids for fid in flood_ids[:10])
    assert all(fid in node._seen_flood_ids for fid in flood_ids[10:])


def test_cap_grows_with_client_count():
    """More clients, more concurrent floods, more room before eviction."""
    node = _make_node(num_clients=30)  # 30 * 100 = 3000
    flood_ids = [str(uuid.uuid4()) for _ in range(2500)]
    _feed(node, flood_ids)

    assert len(node._seen_flood_ids) == 2500


def test_a_repeated_flood_id_is_answered_once():
    node = _make_node(num_clients=3)
    client = next(iter(node.clients.values()))
    flood_id = str(uuid.uuid4())

    node.handle_ping_message(_ping(flood_id, peer="sat-a"), client)
    sends_after_first = sum(c.send.call_count for c in node.clients.values())

    node.handle_ping_message(_ping(flood_id, peer="sat-b"), client)
    assert sum(c.send.call_count for c in node.clients.values()) == sends_after_first


def test_bus_emit_is_one_per_flood_and_peer_not_one_per_arrival():
    """The agent bus sees each (flood_id, peer) observation once.

    The emit used to run on every arrival, ahead of every gate, so a peer that
    reached the node over several mesh paths multiplied agent-bus traffic by
    the mesh fan-out. A new peer inside an already-answered flood is still a
    discovery and must still be emitted.
    """
    node = _make_node(num_clients=1)
    client = next(iter(node.clients.values()))
    flood_id = str(uuid.uuid4())

    node.handle_ping_message(_ping(flood_id, peer="sat-a"), client)
    node.handle_ping_message(_ping(flood_id, peer="sat-a"), client)  # echo
    node.handle_ping_message(_ping(flood_id, peer="sat-b"), client)  # new peer

    emitted = [c.args[0] for c in node.agent_protocol.bus.emit.call_args_list]
    peers = [m.data["peer"] for m in emitted if m.msg_type == "hive.ping.received"]
    assert peers == ["sat-a", "sat-b"]
