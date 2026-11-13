"""The PING flood throttle must not strand the upstream answer.

``ping_flood_interval`` caps how often this node fans a responsive PING out
across the mesh. ``_seen_flood_ids`` is shared with the upstream slave half
(see ``bind_upstream``) and means "this node owes the master an answer for
this flood, and the other half must not send a second one".

Those two features interact, and the order they run in is the whole point of
this module. If the throttle claimed ``_seen_flood_ids`` and then returned,
the answer would be owed by nobody: the throttled half never sends it, and
the slave half stays suppressed because the claim is shared. The master would
silently stop seeing this node — no error, no dropped message, just a node
that quietly falls out of the hive map.

So the throttle is taken first and leaves the claim untouched.
"""
import uuid
from unittest.mock import MagicMock

from hivemind_bus_client.hive_map import FloodIdCache, HiveMapper
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindListenerProtocol


def _make_node(interval: float, num_clients: int = 3) -> HiveMindListenerProtocol:
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
    node.ping_flood_interval = interval
    return node


def _ping(flood_id: str, peer: str = "sat") -> HiveMessage:
    return HiveMessage(HiveMessageType.PING, {
        "flood_id": flood_id,
        "peer": peer,
        "site_id": None,
        "timestamp": 0.0,
    })


class TestThrottledFloodLeavesTheUpstreamClaimAlone:
    """The regression this module exists for."""

    def test_a_throttled_flood_does_not_claim_the_upstream_answer(self):
        node = _make_node(interval=3600.0)
        client = node.clients["peer0"]

        first = str(uuid.uuid4())
        node.handle_ping_message(_ping(first), client)
        # the first flood is not throttled, so it does claim
        assert first in node._seen_flood_ids

        # a second flood arrives inside the window and is throttled
        second = str(uuid.uuid4())
        node.handle_ping_message(_ping(second), client)

        assert second not in node._seen_flood_ids, (
            "a throttled flood must not claim the shared upstream slot: the "
            "throttled half never sends the answer, and the slave half is "
            "suppressed by the claim, so the master never hears from this node"
        )

    def test_the_throttled_flood_still_answers_the_asking_peer(self):
        node = _make_node(interval=3600.0)
        asker = node.clients["peer0"]
        node.handle_ping_message(_ping(str(uuid.uuid4())), asker)
        before = asker.send.call_count

        node.handle_ping_message(_ping(str(uuid.uuid4())), asker)

        assert asker.send.call_count == before + 1, \
            "the peer that asked inside the window is still answered directly"

    def test_a_throttled_flood_does_not_fan_out_to_other_peers(self):
        node = _make_node(interval=3600.0)
        asker = node.clients["peer0"]
        other = node.clients["peer1"]
        node.handle_ping_message(_ping(str(uuid.uuid4())), asker)
        before = other.send.call_count

        node.handle_ping_message(_ping(str(uuid.uuid4())), asker)

        assert other.send.call_count == before, \
            "the mesh-wide fan-out is exactly what the throttle defers"


class TestAnUnthrottledFloodStillBehaves:
    """Positive controls, so the assertions above cannot pass vacuously."""

    def test_an_unthrottled_flood_claims_and_fans_out(self):
        node = _make_node(interval=0.0)
        asker = node.clients["peer0"]
        other = node.clients["peer1"]

        flood_id = str(uuid.uuid4())
        node.handle_ping_message(_ping(flood_id), asker)

        assert flood_id in node._seen_flood_ids
        assert other.send.call_count == 1


class TestRepeatArrivalsOfOneFlood:
    """MSG-1 §4: a flood is answered at most once per half, throttle aside."""

    def test_the_same_flood_id_twice_is_answered_once(self):
        node = _make_node(interval=0.0)
        asker = node.clients["peer0"]
        other = node.clients["peer1"]

        flood_id = str(uuid.uuid4())
        node.handle_ping_message(_ping(flood_id), asker)
        node.handle_ping_message(_ping(flood_id), asker)

        assert other.send.call_count == 1, \
            "the second arrival of the same flood must not re-flood"
