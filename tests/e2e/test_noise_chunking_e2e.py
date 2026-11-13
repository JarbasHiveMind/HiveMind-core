"""Multi-frame Noise chunking e2e: a satellite sends a bus message larger
than a single Noise frame; the hub reassembles it before it hits the agent
bus. Reproduces the voice-relay scenario (a base64-encoded audio blob
attached to ``recognizer_loop:b64_transcribe``) that motivated the
hivemind_bus_client 1.1.0a1 / hivemind-websocket-protocol 1.0.1a1 co-release:
the client now splits an oversized payload into multiple Noise frames on
send, and the hub must reassemble them byte-identical on receive.
"""

import base64
import hashlib
import os
import time

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message

from hivescope.scenarios import admin_satellite

MSG_TYPE = "recognizer_loop:b64_transcribe"


def _wait_for(condition, timeout: float = 5.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


def _b64_blob(nbytes: int) -> str:
    """A deterministic base64 payload of roughly ``nbytes`` raw bytes."""
    raw = os.urandom(nbytes)
    return base64.b64encode(raw).decode("utf-8")


def _round_trip(payload_size: int):
    """Send a single large ``recognizer_loop:b64_transcribe`` bus message
    from a satellite and assert it arrives at the master's agent bus
    byte-identical (same length, same hash) to what was sent.
    """
    b = admin_satellite(allowed_types=[MSG_TYPE])
    try:
        b.start_all()
        m0 = b.get_master("M0")
        s0 = b.get_satellite("S0")

        seen = []
        m0.agent_protocol.bus.on(MSG_TYPE, seen.append)

        audio_b64 = _b64_blob(payload_size)
        sent_hash = hashlib.sha256(audio_b64.encode("utf-8")).hexdigest()

        s0.send(HiveMessage(
            HiveMessageType.BUS,
            payload=Message(MSG_TYPE, {"audio": audio_b64, "lang": "en-us"}),
        ))

        assert _wait_for(lambda: len(seen) >= 1), (
            f"large multi-frame message ({payload_size} bytes) did not "
            f"reach master bus: {seen}"
        )

        received = seen[0].data["audio"]
        assert len(received) == len(audio_b64)
        assert hashlib.sha256(received.encode("utf-8")).hexdigest() == sent_hash
    finally:
        b.stop_all()


def test_large_message_exceeding_single_noise_frame_reassembles_byte_identical():
    """~300KB base64 payload (the voice-relay #45 scenario) exceeds a single
    Noise frame and requires the client to split it into multiple frames and
    the hub to reassemble them.
    """
    _round_trip(300_000)


def test_multi_chunk_ten_second_audio_sized_message_reassembles_byte_identical():
    """~320KB payload, roughly a 10s-audio-sized transcription blob,
    exercising more than two Noise frames of reassembly on the hub side.
    """
    _round_trip(320_000)
