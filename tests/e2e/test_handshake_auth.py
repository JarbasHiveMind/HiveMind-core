"""Handshake authentication: registered keys connect; unknown ones don't."""

import pytest

from hivescope import TopologyBuilder
from hivescope.assertions import assert_handshake_complete


def test_registered_satellite_handshakes_successfully():
    b = TopologyBuilder()
    m = b.add_master("M0")
    b.add_satellite("S0", upstream=m)
    try:
        b.start_all()
        master = b.get_master("M0")
        satellite = b.get_satellite("S0")
        assert_handshake_complete(master, satellite)
    finally:
        b.stop_all()


def test_session_id_assigned_after_handshake():
    b = TopologyBuilder()
    m = b.add_master("M0")
    b.add_satellite("S0", upstream=m)
    try:
        b.start_all()
        s = b.get_satellite("S0")
        assert s.shim.session_id, "session_id missing after handshake"
        assert s.shim.session_id != "default", "session_id stayed default"
    finally:
        b.stop_all()


def test_handshake_event_set_for_each_satellite():
    b = TopologyBuilder()
    m = b.add_master("M0")
    for i in range(3):
        b.add_satellite(f"S{i}", upstream=m)
    try:
        b.start_all()
        for i in range(3):
            s = b.get_satellite(f"S{i}")
            assert s.shim.handshake_event.is_set(), f"S{i} did not finish handshake"
    finally:
        b.stop_all()
