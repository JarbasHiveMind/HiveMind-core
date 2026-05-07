"""Connection lifecycle: peers register and deregister cleanly."""

from hivescope import TopologyBuilder


def test_disconnected_peer_drops_from_connected_peers():
    b = TopologyBuilder()
    m = b.add_master("M0")
    b.add_satellite("S0", upstream=m)
    b.add_satellite("S1", upstream=m)
    b.start_all()
    try:
        m0 = b.get_master("M0")
        s0 = b.get_satellite("S0")

        assert len(m0.connected_peers()) == 2
        s0.disconnect()
        assert s0.peer not in m0.connected_peers()
        assert len(m0.connected_peers()) == 1
    finally:
        b.stop_all()


def test_three_satellites_register_independently():
    from hivescope.scenarios import three_satellites

    b = three_satellites()
    b.start_all()
    try:
        m0 = b.get_master("M0")
        peers = m0.connected_peers()
        assert len(peers) == 3, peers
        assert len(set(peers)) == 3, f"duplicate peer ids: {peers}"
    finally:
        b.stop_all()
