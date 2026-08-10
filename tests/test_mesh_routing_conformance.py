"""Regression tests for HIVEMIND-NODE-1 mesh-routing conformance.

Five related routing defects are pinned here:

* **NODE-1 §3.3 / §4** — a relay MUST preserve the envelope. PROPAGATE and
  BROADCAST fan-out must hand peers a PROPAGATE/BROADCAST envelope, not the
  bare inner message: a peer that receives a bare BUS has nothing to
  re-propagate, so the flood dies after one hop.
* **NODE-1 §5.2 / AGENT-1 §3** — a QUERY/CASCADE *response* belongs to one
  peer. A relay MUST route it back along the return path, never fan it to
  every downstream node.
* **NODE-1 §3.4** — loop prevention applies to the upstream -> downstream
  relay path too, not only to downstream-origin traffic.
* **NODE-1 §3.3** — a relayed ESCALATE/PROPAGATE/CASCADE must keep the outer
  envelope's ``metadata``, ``target_site_id`` and ``target_pubkey``; site
  targeting is read off the outer envelope, so dropping it makes a
  site-targeted message undeliverable after one relay hop.
* **NODE-1 §4** — a responsive PING travels across the whole mesh, upstream
  included.
"""
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from hivemind_bus_client.hive_map import FloodIdCache
from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivemind_bus_client.hive_map import FloodIdCache

from hivemind_core.protocol import HiveMindListenerProtocol

DEFAULT_PEER = "master:0.0.0.0"


def _make_node(node_key: str = "pubkey-A", site_id=None) -> HiveMindListenerProtocol:
    node = object.__new__(HiveMindListenerProtocol)
    node.peer = DEFAULT_PEER
    node.identity = MagicMock(public_key=node_key, site_id=site_id)
    node.clients = {}
    node.illegal_callback = None
    node.propagate_callback = None
    node.escalate_callback = None
    node.broadcast_callback = None
    node._upstream_hm = None
    return node


def _make_client(peer: str) -> MagicMock:
    client = MagicMock()
    client.peer = peer
    client.can_propagate = True
    client.can_escalate = True
    client.is_admin = True
    return client


def _wire_peers(node, *peers):
    """Give ``node`` one recording connection per peer id."""
    sent = {p: [] for p in peers}
    for p in peers:
        conn = MagicMock()
        conn.send = lambda m, box=sent[p]: box.append(m)
        node.clients[p] = conn
    return sent


def _upstream(node):
    captured = []
    node._upstream_hm = MagicMock()
    node._upstream_hm.emit = captured.append
    return captured


def _inner(utt="hi"):
    return HiveMessage(HiveMessageType.BUS,
                       payload=Message("speak", {"utterance": utt}))


def _deliver_preamble(message: HiveMessage, from_peer: str) -> None:
    message.update_source_peer(from_peer)
    message.update_hop_data()


# --- BUG 1: fan-out must preserve the outer envelope (NODE-1 §3.3, §4) ------

def test_propagate_fanout_keeps_the_propagate_envelope():
    """A peer must receive a PROPAGATE it can re-propagate, not a bare BUS."""
    node = _make_node()
    sent = _wire_peers(node, "origin::0", "peer::1")

    msg = HiveMessage(HiveMessageType.PROPAGATE, payload=_inner("flood"))
    _deliver_preamble(msg, "origin::0")
    node.handle_propagate_message(msg, _make_client("origin::0"))

    assert len(sent["peer::1"]) == 1
    fwd = sent["peer::1"][0]
    assert fwd.msg_type == HiveMessageType.PROPAGATE, (
        f"peer received {fwd.msg_type}, so it has nothing to re-propagate")
    assert fwd.payload.msg_type == HiveMessageType.BUS


def test_broadcast_fanout_keeps_the_broadcast_envelope():
    node = _make_node()
    sent = _wire_peers(node, "origin::0", "peer::1")

    msg = HiveMessage(HiveMessageType.BROADCAST, payload=_inner("all"))
    _deliver_preamble(msg, "origin::0")
    node.handle_broadcast_message(msg, _make_client("origin::0"))

    assert len(sent["peer::1"]) == 1
    fwd = sent["peer::1"][0]
    assert fwd.msg_type == HiveMessageType.BROADCAST, (
        f"peer received {fwd.msg_type} instead of a BROADCAST envelope")
    assert fwd.payload.msg_type == HiveMessageType.BUS


# --- BUG 2: responses are for one peer only (NODE-1 §5.2, AGENT-1 §3) ------

def _response(msg_type, originator):
    return HiveMessage(msg_type, payload=_inner("the answer"),
                       metadata={"query_id": "q1", "is_response": True,
                                 "originator_peer": originator})


def test_query_response_from_master_reaches_only_the_originator():
    node = _make_node()
    sent = _wire_peers(node, "asker::1", "sibling::2")

    node.query_from_master(_response(HiveMessageType.QUERY, "asker::1"))

    assert len(sent["asker::1"]) == 1
    assert sent["sibling::2"] == [], (
        "a sibling peer must never see another peer's QUERY answer")


def test_cascade_response_from_master_reaches_only_the_originator():
    node = _make_node()
    node.cascade_select_callback = None
    node._pending_cascades = {}
    sent = _wire_peers(node, "asker::1", "sibling::2")

    node.cascade_from_master(_response(HiveMessageType.CASCADE, "asker::1"))

    assert len(sent["asker::1"]) == 1
    assert sent["sibling::2"] == [], (
        "a sibling peer must never see another peer's CASCADE answer")


def test_query_request_from_master_still_fans_out():
    node = _make_node()
    sent = _wire_peers(node, "sat::1", "sat::2")

    node.query_from_master(HiveMessage(HiveMessageType.QUERY,
                                       payload=_inner("who knows?")))

    assert len(sent["sat::1"]) == 1
    assert len(sent["sat::2"]) == 1


# --- BUG 3: loop prevention on the upstream -> downstream path (§3.4) ------

def test_propagate_from_master_stamps_self_hop():
    node = _make_node("pubkey-R")
    sent = _wire_peers(node, "sat::1")

    node.propagate_from_master(HiveMessage(HiveMessageType.PROPAGATE,
                                           payload=_inner("down")))

    sources = [hop.get("source") for hop in sent["sat::1"][0].route]
    assert "pubkey-R" in sources, f"relay did not name itself; sources={sources}"


def test_propagate_from_master_drops_a_looped_message():
    node = _make_node("pubkey-R")
    sent = _wire_peers(node, "sat::1")

    msg = HiveMessage(HiveMessageType.PROPAGATE, payload=_inner("loop"))
    msg.replace_route([{"source": "pubkey-R", "targets": ["sat::1"]}])
    node.propagate_from_master(msg)

    assert sent["sat::1"] == [], "a PROPAGATE already routed here must not be relayed"


def test_query_from_master_drops_a_looped_request():
    node = _make_node("pubkey-R")
    sent = _wire_peers(node, "sat::1")

    msg = HiveMessage(HiveMessageType.QUERY, payload=_inner("q"))
    msg.replace_route([{"source": "pubkey-R", "targets": ["sat::1"]}])
    node.query_from_master(msg)

    assert sent["sat::1"] == []


def test_cascade_from_master_drops_a_looped_request():
    node = _make_node("pubkey-R")
    sent = _wire_peers(node, "sat::1")

    msg = HiveMessage(HiveMessageType.CASCADE, payload=_inner("c"))
    msg.replace_route([{"source": "pubkey-R", "targets": ["sat::1"]}])
    node.cascade_from_master(msg)

    assert sent["sat::1"] == []


# --- BUG 4: relayed envelopes keep metadata and site targeting (§3.3) ------

def test_relayed_propagate_keeps_target_site_and_metadata():
    node = _make_node()
    captured = _upstream(node)

    msg = HiveMessage(HiveMessageType.PROPAGATE, payload=_inner("sited"),
                      target_site_id="site-b", target_pubkey="key-b",
                      metadata={"trace": "t1"})
    _deliver_preamble(msg, "origin::0")
    node.handle_propagate_message(msg, _make_client("origin::0"))

    assert len(captured) == 1
    up = captured[0]
    assert up.target_site_id == "site-b", "site targeting lost after one relay hop"
    assert up.target_public_key == "key-b"
    assert up.metadata == {"trace": "t1"}


def test_relayed_escalate_keeps_target_site_and_metadata():
    node = _make_node()
    captured = _upstream(node)

    msg = HiveMessage(HiveMessageType.ESCALATE, payload=_inner("up"),
                      target_site_id="site-b", target_pubkey="key-b",
                      metadata={"trace": "t2"})
    _deliver_preamble(msg, "origin::0")
    node.handle_escalate_message(msg, _make_client("origin::0"))

    assert len(captured) == 1
    up = captured[0]
    assert up.target_site_id == "site-b", "site targeting lost after one relay hop"
    assert up.target_public_key == "key-b"
    assert up.metadata == {"trace": "t2"}


def test_relayed_cascade_keeps_target_site():
    node = _make_node()
    node.cascade_select_callback = None
    node._pending_cascades = {}
    node.get_bus = MagicMock(return_value=MagicMock())
    node._answer_query_locally = MagicMock(return_value=False)
    captured = _upstream(node)

    msg = HiveMessage(HiveMessageType.CASCADE, payload=_inner("c"),
                      target_site_id="site-b",
                      metadata={"query_id": "q1", "originator_peer": "origin::0"})
    _deliver_preamble(msg, "origin::0")
    node.handle_cascade_message(msg, _make_client("origin::0"))

    assert len(captured) == 1
    assert captured[0].target_site_id == "site-b"
    assert captured[0].metadata["query_id"] == "q1"


# --- BUG 5: the responsive PING also travels upstream (NODE-1 §4) ----------

def test_responsive_ping_is_also_sent_upstream():
    node = _make_node()
    node.hive_mapper = MagicMock()
    node._seen_flood_ids = FloodIdCache()
    node._answered_floods = FloodIdCache()
    node._last_ping_flood = 0.0
    node.ping_flood_interval = 0.0
    node.agent_protocol = MagicMock()
    sent = _wire_peers(node, "sat::1")
    captured = _upstream(node)

    ping = HiveMessage(HiveMessageType.PING, payload={"flood_id": "f1",
                                                      "peer": "sat::1"})
    node.handle_ping_message(ping, _make_client("sat::1"))

    assert len(sent["sat::1"]) == 1, "responsive PING must reach downstream peers"
    assert len(captured) == 1, "responsive PING must also travel upstream"
    assert captured[0].msg_type == HiveMessageType.PROPAGATE
    assert captured[0].payload.msg_type == HiveMessageType.PING
