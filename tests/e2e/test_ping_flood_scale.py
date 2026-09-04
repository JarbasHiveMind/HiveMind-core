"""A node emits at most one responsive PING flood per interval.

PING is a flood: a node that receives one answers with its own PING carrying
the same ``flood_id``, sent to every peer and upstream (HIVEMIND-NODE-1 §4).
Satellites ping on their own schedules, so with ``n`` satellites on one node
the node used to perform ``n`` fan-outs of ``n`` sends per round — quadratic,
and the point where a large site stops completing rounds at all.

The flood_id cache does not help: each satellite originates a *different*
flood_id, so each one is legitimately new. What is capped here is the node's
own emission rate, across floods.

A satellite that pings inside the window is not ignored. It still gets this
node's answering PING, sent directly to it, so its map is correct and its
keepalive is served — it just does not make the node fan out to everyone else.
"""
import time
import uuid

import pytest

pytest.importorskip("hivescope")

from hivemind_bus_client.message import HiveMessage, HiveMessageType  # noqa: E402
from hivescope.scenarios import star_topology  # noqa: E402

# TEMP: hivescope's in-process shim delivers synchronously and re-enters the
# Noise send-lock now held across the multi-frame chunking send path, which
# deadlocks the relay/flood path. This is a test-harness artifact, not a
# production bug — chunking is verified over real sockets (HiveMind-voice-relay#45).
# Re-enabled by the hivescope async-delivery shim fix.
pytestmark = pytest.mark.xfail(
    run=False,
    reason="hivescope in-process shim re-enters the Noise send-lock (deadlock); "
           "harness fix in hivescope, not a production bug",
)

NUM_SATELLITES = 6


def _ping_from(satellite) -> str:
    flood_id = str(uuid.uuid4())
    inner = HiveMessage(HiveMessageType.PING, {
        "flood_id": flood_id,
        "peer": satellite.name,
        "site_id": None,
        "timestamp": time.time(),
    })
    satellite.send(HiveMessage(HiveMessageType.PROPAGATE, payload=inner))
    return flood_id


def _count_own_pings(protocol):
    """Record how many peers each flood_id was answered to, by flood_id.

    Only the node's *own* responsive PINGs are counted — the forwarding of a
    satellite's PROPAGATE to the other peers is ordinary PROPAGATE routing and
    is not what this limiter governs.
    """
    counts = {}

    for conn in protocol.clients.values():
        original = conn.send

        def recording(message, _original=original):
            payload = message.payload
            if (message.msg_type == HiveMessageType.PROPAGATE
                    and isinstance(payload, HiveMessage)
                    and payload.msg_type == HiveMessageType.PING
                    and payload.payload.get("peer") == protocol._node_id):
                flood_id = payload.payload["flood_id"]
                counts[flood_id] = counts.get(flood_id, 0) + 1
            return _original(message)

        conn.send = recording

    return counts


@pytest.fixture
def star():
    builder = star_topology(num_satellites=NUM_SATELLITES)
    builder.start_all()
    yield builder
    builder.stop_all()


def test_many_satellites_pinging_together_produce_one_flood(star):
    master = star.get_master("M0")
    master.hm_protocol.ping_flood_interval = 3600.0
    counts = _count_own_pings(master.hm_protocol)

    flood_ids = [_ping_from(star.get_satellite(f"S{i}"))
                 for i in range(NUM_SATELLITES)]

    fanned_out = [fid for fid, n in counts.items() if n > 1]
    assert len(fanned_out) == 1

    # every satellite is still answered — the ones inside the window directly
    assert set(counts) == set(flood_ids)
    for fid in flood_ids:
        if fid != fanned_out[0]:
            assert counts[fid] == 1
    assert counts[fanned_out[0]] == NUM_SATELLITES


def test_a_ping_after_the_window_floods_again(star):
    master = star.get_master("M0")
    master.hm_protocol.ping_flood_interval = 0.05
    counts = _count_own_pings(master.hm_protocol)

    first = _ping_from(star.get_satellite("S0"))
    time.sleep(0.1)
    second = _ping_from(star.get_satellite("S1"))

    assert counts[first] == NUM_SATELLITES
    assert counts[second] == NUM_SATELLITES


def test_the_limiter_never_drops_a_satellites_ping(star):
    """Inside the window the asking satellite still receives our PING."""
    master = star.get_master("M0")
    master.hm_protocol.ping_flood_interval = 3600.0

    _ping_from(star.get_satellite("S0"))  # consumes the window

    satellite = star.get_satellite("S1")
    received = []
    satellite.slave_protocol.hm.on(
        HiveMessageType.PROPAGATE, lambda m: received.append(m)
    )
    _ping_from(satellite)

    answers = [m for m in received
               if isinstance(m.payload, HiveMessage)
               and m.payload.msg_type == HiveMessageType.PING
               and m.payload.payload.get("peer") == master.hm_protocol._node_id]
    assert answers
