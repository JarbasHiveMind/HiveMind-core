"""ACL enforcement: blacklisted OVOS message types are dropped before delivery."""

import time

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message

from hivescope.scenarios import single_satellite


def _wait_for(condition, timeout: float = 2.0, interval: float = 0.02) -> bool:
    """Poll ``condition()`` until truthy or until ``timeout`` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


def test_blacklisted_type_not_delivered_to_satellite():
    b = single_satellite()
    try:
        b.start_all()
        m0 = b.get_master("M0")
        s0 = b.get_satellite("S0")

        # Blacklist "speak" on the live connection.
        conn = m0.hm_protocol.clients[s0.peer]
        conn.msg_blacklist = ["speak"]

        seen = []
        s0.shim.emitter.on(
            HiveMessageType.BUS,
            lambda msg: seen.append(msg)
            if isinstance(msg.payload, Message) and msg.payload.msg_type == "speak"
            else None,
        )

        m0.send_to_satellite(
            s0.peer,
            HiveMessage(
                HiveMessageType.BUS,
                payload=Message("speak", {"utterance": "should not arrive"}),
            ),
        )

        # Give any errant delivery a chance to land before asserting absence.
        time.sleep(0.5)
        assert seen == [], f"Blacklisted 'speak' was delivered: {seen}"
    finally:
        b.stop_all()


def test_non_blacklisted_type_still_delivered():
    b = single_satellite()
    try:
        b.start_all()
        m0 = b.get_master("M0")
        s0 = b.get_satellite("S0")

        conn = m0.hm_protocol.clients[s0.peer]
        conn.msg_blacklist = ["speak"]

        seen = []
        s0.shim.emitter.on(HiveMessageType.BUS, seen.append)

        m0.send_to_satellite(
            s0.peer,
            HiveMessage(
                HiveMessageType.BUS,
                payload=Message("recognizer_loop:utterance", {"utterances": ["hi"]}),
            ),
        )

        assert _wait_for(lambda: len(seen) >= 1), f"Message not delivered: {seen}"
        assert len(seen) == 1, f"Unexpected extra deliveries: {seen}"
    finally:
        b.stop_all()
