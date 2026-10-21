"""Mesh e2e: a PROPAGATE must cross a relay and reach the far side.

HIVEMIND-NODE-1 §4 says PROPAGATE fans out across the whole reachable mesh,
and §3.3 says a relay must preserve the envelope. When the master hands its
peers the bare inner message instead of a PROPAGATE, the relay has nothing to
re-propagate and the flood dies one hop from the origin.
"""
import time

import pytest

pytest.importorskip("hivescope")

from hivemind_bus_client.message import HiveMessage, HiveMessageType  # noqa: E402
from ovos_bus_client.message import Message  # noqa: E402
from hivescope.topology import TopologyBuilder  # noqa: E402


def _inner(utt):
    return HiveMessage(HiveMessageType.BUS,
                       payload=Message("speak", {"utterance": utt}))


def test_propagate_from_a_satellite_crosses_the_relay():
    """S1 -> M0 -> R0 -> S0. S0 sits below the relay and must still be reached."""
    b = TopologyBuilder()
    m = b.add_master("M0")
    m.register_satellite("relay-key", password="relay-password")
    m.register_satellite("sat1-key", password="sat1-password")
    relay_side = b.add_relay("R0", upstream=m).listener
    relay_side.register_satellite("sat0-key", password="sat0-password")
    b.add_satellite("S0", upstream=relay_side)
    b.add_satellite("S1", upstream=m)

    b.start_all()
    try:
        received = []
        b.get_satellite("S0").shim.emitter.on(
            HiveMessageType.PROPAGATE, received.append)

        b.get_satellite("S1").send(
            HiveMessage(HiveMessageType.PROPAGATE, payload=_inner("mesh-wide")))
        time.sleep(0.5)

        assert received, ("PROPAGATE never reached the node below the relay — "
                          "the flood died after one hop")
    finally:
        b.stop_all()
