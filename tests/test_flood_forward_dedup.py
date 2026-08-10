"""HIVEMIND-MSG-1 §4: a node drops a flood whose ``flood_id`` it has seen.

The rule was only applied when a node *answered* a flood
(``handle_ping_message``), never when it *forwarded* one. A responsive PING is
built fresh by the answering node — same ``flood_id``, empty ``route`` — so the
§5 route-loop check cannot recognise it, and the master re-fanned every response
to every other peer. One ping round over n satellites then costs the master
n(n-1)^2 sends.

The star mesh below drives the real ``handle_propagate_message`` and counts what
the master puts on the wire, so the growth curve is measured, not asserted from
a formula.
"""
from unittest.mock import MagicMock

from hivemind_bus_client.hive_map import FloodIdCache

from ovos_bus_client.message import Message
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindListenerProtocol


def _make_node(node_key: str = "pubkey-A") -> HiveMindListenerProtocol:
    node = object.__new__(HiveMindListenerProtocol)
    node.peer = "master:0.0.0.0"
    node.identity = MagicMock(public_key=node_key, site_id=None)
    node.clients = {}
    node.illegal_callback = None
    node.propagate_callback = None
    node.escalate_callback = None
    node.broadcast_callback = None
    node._upstream_hm = None
    # FloodIdCache, not a bare set: the caches are size-bounded and
    # check-and-insert atomically, and handle_ping_message calls .check()
    # on them.
    node._seen_flood_ids = FloodIdCache()
    node._answered_floods = FloodIdCache()
    node._forwarded_flood_ids = FloodIdCache()
    node._last_ping_flood = 0.0
    # 0 disables the mesh-wide fan-out throttle: this module is about
    # forward-dedup, and a live throttle would suppress the fan-out these
    # tests are counting.
    node.ping_flood_interval = 0.0
    node.hive_mapper = MagicMock()
    node.agent_protocol = MagicMock()
    return node


def _make_client(peer: str) -> MagicMock:
    client = MagicMock()
    client.peer = peer
    client.can_propagate = True
    client.can_escalate = True
    client.is_admin = True
    return client


def _flood_id_of(message: HiveMessage) -> str:
    """Read a ``flood_id`` off the wire without going through the code we test."""
    inner = message.payload
    if isinstance(inner, HiveMessage):
        inner = inner.payload
    return inner.get("flood_id", "") if isinstance(inner, dict) else ""


def _ping(flood_id: str, peer: str) -> HiveMessage:
    inner = HiveMessage(HiveMessageType.PING,
                        payload={"flood_id": flood_id, "peer": peer})
    return HiveMessage(HiveMessageType.PROPAGATE, payload=inner)


class StarMesh:
    """A master with ``n`` satellites, each of which answers a flood once.

    "Answers once" mirrors the satellite behaviour the mesh converged on: a node
    emits its own responsive PING the first time it sees a ``flood_id``, and
    stays quiet for later copies. Without that the mesh never settles.
    """

    def __init__(self, n: int):
        self.master = _make_node()
        self.sends = 0
        self.pending = []
        self.answered = set()  # (peer, flood_id) pairs already answered
        self.delivered = {}
        for i in range(n):
            peer = f"sat::{i}"
            self.delivered[peer] = []
            conn = MagicMock()
            conn.peer = peer
            conn.send = lambda msg, _plaintext=None, p=peer: self._receive(p, msg)
            self.master.clients[peer] = conn

    def _receive(self, peer: str, message: HiveMessage) -> None:
        """A satellite receives one message from the master."""
        self.sends += 1
        self.delivered[peer].append(message)
        flood_id = _flood_id_of(message)
        if flood_id and (peer, flood_id) not in self.answered:
            self.answered.add((peer, flood_id))
            self.pending.append((peer, _ping(flood_id, peer)))

    def run_round(self) -> int:
        """Every satellite originates one PING; run the mesh to a fixpoint.

        Returns the number of messages the master sent during the round.
        """
        self.sends = 0
        for peer in list(self.master.clients):
            flood_id = f"flood-{peer}"
            # an originator does not answer its own flood, but does answer
            # every flood started by one of its siblings
            self.answered.add((peer, flood_id))
            self.pending.append((peer, _ping(flood_id, peer)))
        while self.pending:
            peer, message = self.pending.pop(0)
            self.master.handle_propagate_message(message, _make_client(peer))
        return self.sends


def test_ping_round_cost_stops_growing_quadratically():
    """The n(n-1)^2 term is gone: cost per round is linear in n per flood.

    Measured on this harness with the forward gate removed: 1000 sends at n=10
    and 8000 at n=20, i.e. n(2n-1 + (n-1)^2). With the gate: 190 and 780.
    """
    counts = {n: StarMesh(n).run_round() for n in (10, 20)}

    # n floods per round, each costing the master (n-1) forwards + n answers
    assert counts[10] == 10 * (2 * 10 - 1)   # 190, was 1000
    assert counts[20] == 20 * (2 * 20 - 1)   # 780, was 8000

    # doubling n used to multiply the round cost by 8; it may now only quadruple
    assert counts[20] < 5 * counts[10]


def test_master_forwards_a_flood_once_no_matter_how_many_copies_arrive():
    mesh = StarMesh(5)
    master = mesh.master
    origin = _make_client("sat::0")

    master.handle_propagate_message(_ping("f1", "sat::0"), origin)
    first_round = mesh.sends

    # the same flood arriving again from a different peer is not re-fanned
    mesh.sends = 0
    master.handle_propagate_message(_ping("f1", "sat::1"), _make_client("sat::1"))
    assert mesh.sends == 0, "an already forwarded flood must not be re-fanned"
    assert first_round > 0


def test_a_new_flood_still_reaches_every_node():
    """The safety case: dedup must never suppress a flood nobody has seen."""
    mesh = StarMesh(6)
    master = mesh.master
    master.handle_propagate_message(_ping("f1", "sat::0"), _make_client("sat::0"))

    for peer, received in mesh.delivered.items():
        if peer == "sat::0":
            continue
        assert received, f"{peer} never saw the flood"

    # a second, genuinely different flood is not mistaken for the first
    mesh.sends = 0
    master.handle_propagate_message(_ping("f2", "sat::1"), _make_client("sat::1"))
    assert mesh.sends > 0, "a new flood_id must still be forwarded"


def test_message_without_flood_id_is_always_forwarded():
    """Untagged traffic keeps working exactly as before — no dedup applies."""
    mesh = StarMesh(3)
    master = mesh.master
    inner = HiveMessage(HiveMessageType.BUS,
                        payload=Message("speak", {"utterance": "hi"}))

    for _ in range(3):
        mesh.sends = 0
        msg = HiveMessage(HiveMessageType.PROPAGATE, payload=inner)
        msg.update_source_peer("sat::0")
        msg.update_hop_data()
        master.handle_propagate_message(msg, _make_client("sat::0"))
        assert mesh.sends == 2, "a message with no flood_id must never be dropped"


def test_relay_downstream_drops_an_already_relayed_flood():
    """The upstream -> downstream relay path carries floods too."""
    node = _make_node("relay-key")
    sent = []
    conn = MagicMock()
    conn.peer = "sat::0"
    # send(message, plaintext): the relay serializes once for the whole
    # fan-out, so the stub takes and discards the second argument.
    conn.send = lambda msg, _plaintext=None: sent.append(msg)
    node.clients["sat::0"] = conn

    node._relay_downstream(_ping("f1", "origin"))
    assert len(sent) == 1

    node._relay_downstream(_ping("f1", "origin"))
    assert len(sent) == 1, "relay must not re-fan an already relayed flood"

    node._relay_downstream(_ping("f2", "origin"))
    assert len(sent) == 2, "a new flood must still be relayed"
