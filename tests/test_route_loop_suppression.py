"""Regression tests for HIVEMIND-MSG-1 §5 routing-loop suppression.

MSG-1 §5 requires that a node forwarding a routing message (PROPAGATE,
ESCALATE, CASCADE, PING):

* **MUST** append a hop naming itself to ``route``; and
* **MUST NOT** forward a message whose ``route`` already contains a hop
  naming it, to prevent loops.

Before this fix ``handle_propagate_message`` (and the ESCALATE/CASCADE
forward paths) did neither: in a cyclic topology a PROPAGATE re-broadcast
forever. These tests assert the self-hop append and the drop-on-loop
behaviour, including a 3-node ring that must terminate.

Surfaced by the hivemind-test-harness spec-MUST suite, which strict-xfails
this as a known gap; this fix flips it.
"""
from collections import deque
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindListenerProtocol


def _make_node(peer: str) -> HiveMindListenerProtocol:
    node = object.__new__(HiveMindListenerProtocol)
    node.peer = peer
    node.clients = {}
    node.identity = MagicMock(site_id=None)
    node.illegal_callback = None
    node.propagate_callback = MagicMock()
    node.escalate_callback = MagicMock()
    node._upstream_hm = None
    return node


def _make_client(peer: str) -> MagicMock:
    client = MagicMock()
    client.peer = peer
    client.can_propagate = True
    client.can_escalate = True
    return client


def _propagate(utt: str) -> HiveMessage:
    inner = HiveMessage(HiveMessageType.BUS,
                        payload=Message("speak", {"utterance": utt}))
    return HiveMessage(HiveMessageType.PROPAGATE, payload=inner)


def _deliver_preamble(message: HiveMessage, from_peer: str) -> None:
    """Replicate the ``handle_message`` preamble a real node runs before
    dispatching to ``handle_propagate_message``."""
    message.update_source_peer(from_peer)
    message.update_hop_data()


def test_propagate_appends_self_hop_when_forwarding():
    """MSG-1 §5: a forwarded PROPAGATE must carry a hop naming this node."""
    node = _make_node("N::1")
    sent = []
    conn = MagicMock()
    conn.send = lambda m: sent.append(m)
    node.clients = {"peerB::9": conn}

    msg = _propagate("hi")
    _deliver_preamble(msg, "origin::0")
    node.handle_propagate_message(msg, _make_client("origin::0"))

    assert len(sent) == 1, "message should be forwarded to the one downstream peer"
    forwarded = sent[0]
    sources = [hop.get("source") for hop in forwarded.route]
    assert "N::1" in sources, f"self-hop not appended; route sources={sources}"


def test_propagate_dropped_when_already_routed():
    """MSG-1 §5: a PROPAGATE whose route already names this node is dropped —
    not re-broadcast and not re-processed."""
    node = _make_node("N::1")
    sent = []
    conn = MagicMock()
    conn.send = lambda m: sent.append(m)
    node.clients = {"peerB::9": conn}

    msg = _propagate("loop")
    # simulate the message having already passed through this node
    msg.replace_route([{"source": "N::1", "targets": ["peerB::9"]}])
    _deliver_preamble(msg, "peerC::7")

    node.handle_propagate_message(msg, _make_client("peerC::7"))

    assert sent == [], "already-routed message must NOT be re-broadcast"
    node.propagate_callback.assert_not_called()


def test_propagate_ring_terminates():
    """3-node ring N0 -> N1 -> N2 -> N0: a PROPAGATE must die when it returns
    to a node already in its route. Each node forwards it at most once."""
    n0 = _make_node("N0::1")
    n1 = _make_node("N1::1")
    n2 = _make_node("N2::1")

    queue: deque = deque()
    forwards = {n0.peer: 0, n1.peer: 0, n2.peer: 0}

    def wire(src_node, dst_node):
        """src_node.clients[dst.peer] -> re-wrap the unwrapped payload as a
        PROPAGATE (carrying the accumulated route) and enqueue for dst."""
        def send(payload):
            forwards[src_node.peer] += 1
            outer = HiveMessage(HiveMessageType.PROPAGATE, payload=payload)
            outer.replace_route(payload.route)
            queue.append((dst_node, outer, src_node.peer))
        conn = MagicMock()
        conn.send = send
        src_node.clients = {dst_node.peer: conn}

    wire(n0, n1)
    wire(n1, n2)
    wire(n2, n0)

    seed = _propagate("ring")
    queue.append((n0, seed, "origin::0"))

    steps = 0
    while queue:
        steps += 1
        assert steps <= 50, "ring did not terminate — routing loop not suppressed"
        node, msg, from_peer = queue.popleft()
        _deliver_preamble(msg, from_peer)
        node.handle_propagate_message(msg, _make_client(from_peer))

    # each of the 3 nodes forwards the message exactly once; when it comes back
    # to n0 (already in the route) it is dropped -> 3 total forwards, no flood
    assert forwards == {"N0::1": 1, "N1::1": 1, "N2::1": 1}, forwards


def test_escalate_appends_self_hop_and_drops_on_loop():
    """MSG-1 §5 applies equally to ESCALATE forwarding."""
    # forwarding appends a self-hop onto the upstream-bound payload
    node = _make_node("E::1")
    captured = []
    node._upstream_hm = MagicMock()
    node._upstream_hm.emit = lambda m: captured.append(m)

    msg = _propagate("up")  # reuse builder, swap the outer type
    msg = HiveMessage(HiveMessageType.ESCALATE, payload=msg.payload)
    _deliver_preamble(msg, "origin::0")
    node.handle_escalate_message(msg, _make_client("origin::0"))

    assert len(captured) == 1
    sources = [hop.get("source") for hop in captured[0].route]
    assert "E::1" in sources, f"self-hop not appended upstream; sources={sources}"

    # a looped ESCALATE is dropped (nothing forwarded upstream)
    node2 = _make_node("E::1")
    captured2 = []
    node2._upstream_hm = MagicMock()
    node2._upstream_hm.emit = lambda m: captured2.append(m)
    looped = HiveMessage(HiveMessageType.ESCALATE, payload=_propagate("x").payload)
    looped.replace_route([{"source": "E::1", "targets": ["p::2"]}])
    _deliver_preamble(looped, "peer::2")
    node2.handle_escalate_message(looped, _make_client("peer::2"))
    assert captured2 == [], "already-routed ESCALATE must not be forwarded upstream"
