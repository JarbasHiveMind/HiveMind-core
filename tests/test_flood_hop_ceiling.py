"""HIVEMIND-NODE-1 §4 scale boundary.

"A deployment running a large or densely cross-connected mesh SHOULD bound a
flood by the length of the message's route, refusing to forward a message
that already carries more than a configured number of hops." The route is the
only hop record on the wire. ``max_flood_hops`` is that ceiling; 0 leaves the
flood unbounded.
"""
from unittest.mock import MagicMock

from hivemind_bus_client.hive_map import FloodIdCache
from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message

from hivemind_core.protocol import HiveMindListenerProtocol


def _make_node(max_flood_hops: int) -> HiveMindListenerProtocol:
    node = object.__new__(HiveMindListenerProtocol)
    node.peer = "master:0.0.0.0"
    node.identity = MagicMock(public_key="pubkey-A", site_id=None)
    node.clients = {}
    node.illegal_callback = None
    node.propagate_callback = None
    node.broadcast_callback = None
    node._upstream_hm = None
    node._seen_flood_ids = FloodIdCache()
    node._answered_floods = FloodIdCache()
    node._forwarded_flood_ids = FloodIdCache()
    node._last_ping_flood = 0.0
    node.ping_flood_interval = 0.0
    node.max_flood_hops = max_flood_hops
    node.hive_mapper = MagicMock()
    node.agent_protocol = MagicMock()
    return node


def _peer(peer: str) -> MagicMock:
    client = MagicMock()
    client.peer = peer
    client.can_propagate = True
    client.can_broadcast = True
    client.is_admin = True
    # a real ``HiveMindClientConnection`` starts every connection with this
    # False; MagicMock would otherwise auto-vivify it as a truthy Mock and
    # every refusal would look like a repeat.
    client._flood_ceiling_warned = False
    return client


def _propagate(hops: int) -> HiveMessage:
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("speak", {"utterance": "hi"}))
    route = [{"source": f"node-{i}", "targets": [f"node-{i + 1}"]} for i in range(hops)]
    return HiveMessage(HiveMessageType.PROPAGATE, payload=inner, route=route)


def _broadcast(hops: int) -> HiveMessage:
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("speak", {"utterance": "hi"}))
    route = [{"source": f"node-{i}", "targets": [f"node-{i + 1}"]} for i in range(hops)]
    return HiveMessage(HiveMessageType.BROADCAST, payload=inner, route=route)


def _fan_out(node, handler, message):
    origin = _peer("sat-origin")
    others = [_peer("sat-1"), _peer("sat-2")]
    node.clients = {c.peer: c for c in [origin] + others}
    handler(message, origin)
    return sum(c.send.call_count for c in others)


def test_a_propagate_past_the_ceiling_is_not_forwarded():
    node = _make_node(max_flood_hops=1)
    assert _fan_out(node, node.handle_propagate_message, _propagate(hops=2)) == 0


def test_a_propagate_at_the_ceiling_is_forwarded():
    node = _make_node(max_flood_hops=1)
    assert _fan_out(node, node.handle_propagate_message, _propagate(hops=1)) == 2


def test_a_broadcast_past_the_ceiling_is_not_forwarded():
    node = _make_node(max_flood_hops=1)
    assert _fan_out(node, node.handle_broadcast_message, _broadcast(hops=2)) == 0


def test_zero_leaves_the_flood_unbounded():
    node = _make_node(max_flood_hops=0)
    assert _fan_out(node, node.handle_propagate_message, _propagate(hops=7)) == 2


def test_local_delivery_still_runs_past_the_ceiling():
    node = _make_node(max_flood_hops=1)
    node.propagate_callback = MagicMock()
    _fan_out(node, node.handle_propagate_message, _propagate(hops=3))
    node.propagate_callback.assert_called_once()


def _relay_fan_out(node, handler, message):
    peers = [_peer("sat-1"), _peer("sat-2")]
    node.clients = {c.peer: c for c in peers}
    handler(message)
    return sum(c.send.call_count for c in peers)


def test_a_relay_does_not_pass_a_propagate_from_its_master_past_the_ceiling():
    node = _make_node(max_flood_hops=1)
    assert _relay_fan_out(node, node.propagate_from_master, _propagate(hops=2)) == 0
    assert _relay_fan_out(node, node.propagate_from_master, _propagate(hops=1)) == 2


def test_a_relay_does_not_pass_a_broadcast_from_its_master_past_the_ceiling():
    node = _make_node(max_flood_hops=1)
    assert _relay_fan_out(node, node.broadcast_from_master, _broadcast(hops=2)) == 0
    assert _relay_fan_out(node, node.broadcast_from_master, _broadcast(hops=1)) == 2


def test_the_first_refusal_on_a_connection_is_logged_at_info(caplog):
    node = _make_node(max_flood_hops=1)
    origin = _peer("sat-origin")
    node.clients = {origin.peer: origin}
    with caplog.at_level("DEBUG"):
        node.handle_propagate_message(_propagate(hops=2), origin)

    info_records = [r for r in caplog.records if r.levelname == "INFO"]
    assert len(info_records) == 1
    assert "PROPAGATE" in info_records[0].message
    assert "sat-origin" in info_records[0].message


def test_a_second_refusal_on_the_same_connection_stays_at_debug(caplog):
    node = _make_node(max_flood_hops=1)
    origin = _peer("sat-origin")
    node.clients = {origin.peer: origin}
    with caplog.at_level("DEBUG"):
        node.handle_propagate_message(_propagate(hops=2), origin)
        node.handle_propagate_message(_propagate(hops=2), origin)

    info_records = [r for r in caplog.records if r.levelname == "INFO"]
    assert len(info_records) == 1


def test_a_refusal_on_a_different_connection_gets_its_own_info_record(caplog):
    node = _make_node(max_flood_hops=1)
    origin_a = _peer("sat-a")
    origin_b = _peer("sat-b")
    node.clients = {origin_a.peer: origin_a, origin_b.peer: origin_b}
    with caplog.at_level("DEBUG"):
        node.handle_propagate_message(_propagate(hops=2), origin_a)
        node.handle_propagate_message(_propagate(hops=2), origin_b)

    info_records = [r for r in caplog.records if r.levelname == "INFO"]
    assert len(info_records) == 2
    assert any("sat-a" in r.message for r in info_records)
    assert any("sat-b" in r.message for r in info_records)


def test_the_first_master_relay_refusal_is_logged_at_info(caplog):
    node = _make_node(max_flood_hops=1)
    with caplog.at_level("DEBUG"):
        _relay_fan_out(node, node.propagate_from_master, _propagate(hops=2))

    info_records = [r for r in caplog.records if r.levelname == "INFO"]
    assert len(info_records) == 1
    assert "PROPAGATE" in info_records[0].message


def test_a_second_master_relay_refusal_stays_at_debug(caplog):
    node = _make_node(max_flood_hops=1)
    with caplog.at_level("DEBUG"):
        _relay_fan_out(node, node.propagate_from_master, _propagate(hops=2))
        _relay_fan_out(node, node.propagate_from_master, _propagate(hops=2))

    info_records = [r for r in caplog.records if r.levelname == "INFO"]
    assert len(info_records) == 1
