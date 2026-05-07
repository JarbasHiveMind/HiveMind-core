"""Smoke test verifying hivescope wiring against HiveMind-core."""

from hivescope.scenarios import single_satellite
from hivescope.assertions import assert_handshake_complete


def test_hivescope_wiring_handshake():
    """A single-satellite topology completes a handshake end-to-end."""
    builder = single_satellite()
    builder.start_all()
    try:
        master = builder.get_master("M0")
        satellite = builder.get_satellite("S0")
        assert_handshake_complete(master, satellite)
    finally:
        builder.stop_all()
