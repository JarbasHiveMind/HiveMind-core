"""Satellite → master agent bus: BUS messages from a satellite are emitted on the master's bus."""

import time

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message

from hivescope.scenarios import admin_satellite


def _wait_for(condition, timeout: float = 2.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


def test_satellite_bus_message_reaches_master_bus():
    """A satellite-injected ``recognizer_loop:utterance`` reaches the master's agent bus."""
    b = admin_satellite(allowed_types=["recognizer_loop:utterance"])
    try:
        b.start_all()
        m0 = b.get_master("M0")
        s0 = b.get_satellite("S0")

        seen = []
        m0.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)

        s0.send(HiveMessage(
            HiveMessageType.BUS,
            payload=Message("recognizer_loop:utterance",
                            {"utterances": ["hello hive"]}),
        ))

        assert _wait_for(lambda: len(seen) >= 1), f"BUS message did not reach master: {seen}"
        assert seen[0].data["utterances"] == ["hello hive"]
    finally:
        b.stop_all()


def test_satellite_session_id_attached_to_inbound_bus_messages():
    """Master-side bus message context carries a session_id — but it is the
    bridge's own per-connection Layer-1 id, not the satellite's chosen one
    (HIVEMIND-BRIDGE-1 §4): session_id is an orchestrator-side identity that
    OVOS SessionManager keys conversational state on, so the client-chosen
    value is translated at the inbound boundary.
    """
    b = admin_satellite(allowed_types=["recognizer_loop:utterance"])
    try:
        b.start_all()
        m0 = b.get_master("M0")
        s0 = b.get_satellite("S0")

        seen = []
        m0.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)

        s0.send(HiveMessage(
            HiveMessageType.BUS,
            payload=Message("recognizer_loop:utterance",
                            {"utterances": ["hi"]}),
        ))

        assert _wait_for(lambda: len(seen) >= 1)
        ctx = seen[0].context.get("session", {})
        assert ctx.get("session_id"), f"session_id missing: {ctx}"
        assert ctx.get("session_id") != s0.shim.session_id, (
            f"session_id should be translated to a Layer-1 id, not the "
            f"satellite's own: {ctx}"
        )
    finally:
        b.stop_all()
