"""Relay e2e: a dual-role node bound via ``bind_upstream`` forwards downstream
PROPAGATE/ESCALATE up to its master. Exercises HiveMindListenerProtocol's
bind_upstream + escalate_to_master / propagate_to_master path.
"""
import time

import pytest

pytest.importorskip("hivescope")

from hivemind_bus_client.message import HiveMessage, HiveMessageType  # noqa: E402
from ovos_bus_client.message import Message  # noqa: E402
from hivescope.topology import TopologyBuilder  # noqa: E402
from hivescope.assertions import (  # noqa: E402
    assert_escalate_delivered,
    assert_propagate_delivered,
)


def _inner(utt):
    return HiveMessage(HiveMessageType.BUS,
                       payload=Message("speak", {"utterance": utt}))


def _relay_chain():
    """M0 -> R0 (relay) -> S0, built directly (the bundled chain_topology
    scenario predates add_relay returning a RelayNode)."""
    b = TopologyBuilder()
    m = b.add_master("M0")
    m.register_satellite("relay-key", password="relay-password")
    master_side = b.add_relay("R0", upstream=m).listener
    master_side.register_satellite("sat-key", password="sat-password")
    b.add_satellite("S0", upstream=master_side)
    return b


def test_escalate_forwarded_up_the_relay_chain():
    b = _relay_chain()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")
        s.send(HiveMessage(HiveMessageType.ESCALATE, payload=_inner("up")))
        time.sleep(0.3)
        assert_escalate_delivered(m, count=1)
    finally:
        b.stop_all()


def test_propagate_forwarded_up_the_relay_chain():
    b = _relay_chain()
    b.start_all()
    try:
        m = b.get_master("M0")
        s = b.get_satellite("S0")
        s.send(HiveMessage(HiveMessageType.PROPAGATE, payload=_inner("around")))
        time.sleep(0.3)
        assert_propagate_delivered(m, count=1)
    finally:
        b.stop_all()
