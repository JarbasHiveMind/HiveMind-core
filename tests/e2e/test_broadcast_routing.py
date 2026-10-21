"""BROADCAST and routing: master's send_to_all + send_to_satellite hit the right peers."""

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message

from hivescope.scenarios import three_satellites


def _bus_msg(msg_type: str = "test.event", data=None):
    return HiveMessage(
        HiveMessageType.BUS,
        payload=Message(msg_type, data or {"ping": "pong"}),
    )


def test_send_to_satellite_targets_only_recipient():
    b = three_satellites()
    try:
        b.start_all()
        m0 = b.get_master("M0")

        received = {f"S{i}": [] for i in range(3)}
        for i in range(3):
            sat = b.get_satellite(f"S{i}")
            sat.shim.emitter.on(
                HiveMessageType.BUS,
                lambda msg, name=f"S{i}": received[name].append(msg),
            )

        m0.send_to_satellite(b.get_satellite("S1").peer, _bus_msg())

        assert received["S0"] == [], f"S0 should not receive: {received['S0']}"
        assert len(received["S1"]) == 1, f"S1 missed message: {received['S1']}"
        assert received["S2"] == [], f"S2 should not receive: {received['S2']}"
    finally:
        b.stop_all()


def test_send_to_all_reaches_every_peer():
    b = three_satellites()
    try:
        b.start_all()
        m0 = b.get_master("M0")

        received = {f"S{i}": [] for i in range(3)}
        for i in range(3):
            sat = b.get_satellite(f"S{i}")
            sat.shim.emitter.on(
                HiveMessageType.BUS,
                lambda msg, name=f"S{i}": received[name].append(msg),
            )

        m0.send_to_all(_bus_msg("notify", {"id": 42}))

        for name in ("S0", "S1", "S2"):
            assert len(received[name]) == 1, f"{name} missed broadcast: {received[name]}"


    finally:
        b.stop_all()
