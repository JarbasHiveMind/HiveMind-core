"""Regression tests for HIVEMIND-MSG-1 §5 routing-loop suppression.

MSG-1 §5 requires that a node forwarding a routing message (PROPAGATE,
ESCALATE, CASCADE, PING):

* **MUST** append a hop naming itself to ``route``; and
* **MUST NOT** *re-forward* a message whose ``route`` already contains a hop
  naming it, to prevent loops. Local delivery of such a message is not
  forbidden — only its re-forwarding.

The loop-detection identity is the node's **public key**
(``NodeIdentity.public_key``) — the only identifier that is unique per node
*and* stable across connections. Crucially it is **not** ``self.peer``: that
field is the class default ``"master:0.0.0.0"`` that ``service.py`` never
overrides, so in a real deployment every node shares it. Keying loop detection
off ``self.peer`` makes every node see every other node's hop as "me" and
false-drops legitimate multi-hop traffic at the second relay. These tests
construct nodes the way production does (shared default ``self.peer``, distinct
public keys) so they exercise that failure directly: a >=2-relay delivery chain
must survive, and a true cycle must still terminate.
"""
from collections import deque
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindListenerProtocol

# HiveMindListenerProtocol.peer is a class default that service.py never sets,
# so every real node shares this exact value. The tests give every node this
# same placeholder on purpose — the per-node identity comes from the public key.
DEFAULT_PEER = "master:0.0.0.0"


def _make_node(node_key: str, peer: str = DEFAULT_PEER) -> HiveMindListenerProtocol:
    """Build a listener the way production does: a shared placeholder ``peer``
    and a unique per-node ``identity.public_key``."""
    node = object.__new__(HiveMindListenerProtocol)
    node.peer = peer
    node.identity = MagicMock(public_key=node_key, site_id=None)
    node.clients = {}
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
    dispatching to the type handler: stamp the sender connection peer and
    append its return-path hop."""
    message.update_source_peer(from_peer)
    message.update_hop_data()


def test_propagate_appends_self_hop_keyed_on_public_key():
    """MSG-1 §5: a forwarded PROPAGATE must carry a hop naming this node — and
    that hop is keyed on the node's public key, not the shared ``self.peer``."""
    node = _make_node("pubkey-A")
    sent = []
    conn = MagicMock()
    conn.send = lambda m: sent.append(m)
    node.clients = {"downstream::9": conn}

    msg = _propagate("hi")
    _deliver_preamble(msg, "origin::0")
    node.handle_propagate_message(msg, _make_client("origin::0"))

    assert len(sent) == 1, "message should be forwarded to the one downstream peer"
    sources = [hop.get("source") for hop in sent[0].route]
    assert "pubkey-A" in sources, f"self-hop not appended; route sources={sources}"
    # the self-hop is the node identity, NOT the placeholder peer
    assert DEFAULT_PEER not in sources, (
        f"self-hop must not be keyed on the shared placeholder peer; sources={sources}")


def test_multirelay_chain_delivers_under_shared_default_peer():
    """THE regression test. origin -> A -> B -> C, every node carrying the
    shared default ``self.peer`` (as production does). A legitimate PROPAGATE
    must survive both relays and be delivered at C.

    Against the OLD fix (loop keyed on ``self.peer``) B sees A's self-hop
    ``{"source": "master:0.0.0.0"}`` == its own ``self.peer`` and false-drops
    the message, so C never receives it -> this test FAILS. With the identity
    keyed on the public key, B forwards and C delivers -> PASSES.
    """
    a = _make_node("pubkey-A")
    b = _make_node("pubkey-B")
    c = _make_node("pubkey-C")

    queue: deque = deque()
    delivered = {}

    def wire(src_node, dst_node, edge):
        def send(payload):
            outer = HiveMessage(HiveMessageType.PROPAGATE, payload=payload)
            outer.replace_route(payload.route)
            queue.append((dst_node, outer, edge))
        conn = MagicMock()
        conn.send = send
        src_node.clients = {edge: conn}

    wire(a, b, "edge-ab")
    wire(b, c, "edge-bc")
    # c is a leaf; record local delivery instead of forwarding
    c.propagate_callback = MagicMock(side_effect=lambda pl: delivered.setdefault("c", pl))

    seed = _propagate("relayed hello")
    queue.append((a, seed, "origin::0"))

    steps = 0
    while queue:
        steps += 1
        assert steps <= 20, "chain did not settle"
        node, msg, from_peer = queue.popleft()
        _deliver_preamble(msg, from_peer)
        node.handle_propagate_message(msg, _make_client(from_peer))

    assert "c" in delivered, (
        "PROPAGATE was dropped before reaching C — a legitimate multi-relay "
        "chain must not be treated as a loop")
    a.propagate_callback.assert_called_once()
    b.propagate_callback.assert_called_once()


def test_looped_propagate_delivers_locally_but_is_not_reforwarded():
    """MSG-1 §5 forbids *re-forwarding* a looped message, not local handling.
    A PROPAGATE whose route already names this node is delivered locally
    (propagate_callback fires) but is NOT re-broadcast to peers."""
    node = _make_node("pubkey-A")
    sent = []
    conn = MagicMock()
    conn.send = lambda m: sent.append(m)
    node.clients = {"downstream::9": conn}

    msg = _propagate("loop")
    # simulate the message having already passed through this node (its pubkey
    # is already in the route)
    msg.replace_route([{"source": "pubkey-A", "targets": ["downstream::9"]}])
    _deliver_preamble(msg, "peerC::7")

    node.handle_propagate_message(msg, _make_client("peerC::7"))

    assert sent == [], "already-routed message must NOT be re-broadcast"
    node.propagate_callback.assert_called_once()  # local delivery still runs


def test_propagate_ring_terminates():
    """3-node ring A -> B -> C -> A, all sharing the default ``self.peer`` but
    with distinct public keys: a PROPAGATE must die when it returns to a node
    already in its route. Each node re-forwards it at most once."""
    a = _make_node("pubkey-A")
    b = _make_node("pubkey-B")
    c = _make_node("pubkey-C")

    queue: deque = deque()
    forwards = {"pubkey-A": 0, "pubkey-B": 0, "pubkey-C": 0}

    def wire(src_node, dst_node, edge):
        def send(payload):
            forwards[src_node.identity.public_key] += 1
            outer = HiveMessage(HiveMessageType.PROPAGATE, payload=payload)
            outer.replace_route(payload.route)
            queue.append((dst_node, outer, edge))
        conn = MagicMock()
        conn.send = send
        src_node.clients = {edge: conn}

    wire(a, b, "edge-ab")
    wire(b, c, "edge-bc")
    wire(c, a, "edge-ca")

    seed = _propagate("ring")
    queue.append((a, seed, "origin::0"))

    steps = 0
    while queue:
        steps += 1
        assert steps <= 50, "ring did not terminate — routing loop not suppressed"
        node, msg, from_peer = queue.popleft()
        _deliver_preamble(msg, from_peer)
        node.handle_propagate_message(msg, _make_client(from_peer))

    # A, B, C each forward once; when it returns to A (already in the route) it
    # is not re-forwarded -> 3 total forwards, no flood
    assert forwards == {"pubkey-A": 1, "pubkey-B": 1, "pubkey-C": 1}, forwards


def test_escalate_appends_self_hop_and_drops_on_loop():
    """MSG-1 §5 applies equally to ESCALATE forwarding — keyed on public key."""
    # forwarding appends a self-hop (public key) onto the upstream-bound payload
    node = _make_node("pubkey-E")
    captured = []
    node._upstream_hm = MagicMock()
    node._upstream_hm.emit = lambda m: captured.append(m)

    msg = HiveMessage(HiveMessageType.ESCALATE, payload=_propagate("up").payload)
    _deliver_preamble(msg, "origin::0")
    node.handle_escalate_message(msg, _make_client("origin::0"))

    assert len(captured) == 1
    sources = [hop.get("source") for hop in captured[0].route]
    assert "pubkey-E" in sources, f"self-hop not appended upstream; sources={sources}"

    # a looped ESCALATE is not forwarded upstream, but is still delivered locally
    node2 = _make_node("pubkey-E")
    captured2 = []
    node2._upstream_hm = MagicMock()
    node2._upstream_hm.emit = lambda m: captured2.append(m)
    looped = HiveMessage(HiveMessageType.ESCALATE, payload=_propagate("x").payload)
    looped.replace_route([{"source": "pubkey-E", "targets": ["p::2"]}])
    _deliver_preamble(looped, "peer::2")
    node2.handle_escalate_message(looped, _make_client("peer::2"))
    assert captured2 == [], "already-routed ESCALATE must not be forwarded upstream"
    node2.escalate_callback.assert_called_once()  # local delivery still runs
