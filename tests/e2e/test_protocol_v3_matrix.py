"""Protocol v2/v3 migration matrix (HIVEMIND-CRYPTO-1 §3.4, HIVEMIND-WIRE-1 §2).

End-to-end over a real websocket, real master + real client:

- v3 client ↔ v3 server: Noise session established, messages round-trip both ways
- v3 client ↔ v2 server: negotiates down to the legacy handshake, works
- v2 client ↔ v3 server: server accepts the legacy handshake, works
- wrong password: the v3 handshake fails fast, no session, no fallback
- tampered negotiation (downgrade attempt): prologue mismatch aborts the handshake
- replayed v3 transport message: rejected, session torn down
"""

import time
from unittest.mock import patch

import pytest
from ovos_bus_client.message import Message
from websocket import ABNF

import hivemind_core.protocol as server_protocol
from hivemind_bus_client.client import HiveMessageBusClient
from hivemind_bus_client.identity import NodeIdentity
from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivemind_bus_client.protocol import HiveMindSlaveProtocol
from hivescope import TopologyBuilder


def _wait_for(condition, timeout: float = 10.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


def _make_client(url, key, password, name="v3-matrix-client",
                 max_protocol_version=3):
    host, port = url.replace("ws://", "").rstrip("/").split(":")
    port = int(port)
    identity = NodeIdentity()
    identity.access_key = key
    identity.password = password
    identity.default_master = f"ws://{host}"
    identity.default_port = port
    identity.name = name
    identity.site_id = f"{name}-site"
    return HiveMessageBusClient(
        key=key, password=password,
        host=f"ws://{host}", port=port,
        useragent=name, self_signed=False,
        identity=identity,
        max_protocol_version=max_protocol_version,
    )


def _master(key="matrix-key", password="matrix-pwd",
            allowed_types=("recognizer_loop:utterance",)):
    b = TopologyBuilder()
    m = b.add_master("M0", use_loopback=True)
    m.register_satellite(key, password=password,
                         allowed_types=list(allowed_types))
    return b, m


def _assert_round_trip(client, m):
    """BUS messages cross the session in both directions."""
    seen = []
    m.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)
    client.emit(HiveMessage(
        HiveMessageType.BUS,
        payload=Message("recognizer_loop:utterance",
                        {"utterances": ["v3 matrix ping"]}),
    ))
    assert _wait_for(lambda: len(seen) >= 1), "client->master BUS never arrived"
    assert seen[0].data["utterances"] == ["v3 matrix ping"]

    received = []
    client.on_mycroft("speak", received.append)
    peer = next(p for p in m.connected_peers())
    m.send_to_satellite(peer, HiveMessage(
        HiveMessageType.BUS,
        payload=Message("speak", {"utterance": "matrix pong"}),
    ))
    assert _wait_for(lambda: len(received) >= 1), "master->client BUS never arrived"
    assert received[0].data["utterance"] == "matrix pong"


# ─────────────────────────────────────────────── v3 ↔ v3 ──


def test_v3_client_v3_server_noise_session_round_trip():
    b, m = _master()
    try:
        b.start_all()
        client = _make_client(m.network_protocol.url, "matrix-key", "matrix-pwd")
        client.connect(site_id="matrix-site")
        client.wait_for_handshake(timeout=10)
        # protocol v3 negotiated: Noise transport replaces the v2 AES session
        assert client.noise_transport is not None
        assert client.crypto_key is None
        _assert_round_trip(client, m)
        client.close()
    finally:
        b.stop_all()


# ─────────────────────────────────────────────── v3 ↔ v2 ──


def test_v3_client_v2_server_negotiates_down_to_legacy(monkeypatch):
    # a pre-v3 server never advertises Noise support
    monkeypatch.setattr(server_protocol, "NOISE_SUPPORTED", False)
    b, m = _master()
    try:
        b.start_all()
        client = _make_client(m.network_protocol.url, "matrix-key", "matrix-pwd")
        client.connect(site_id="matrix-site")
        client.wait_for_handshake(timeout=10)
        # legacy (v2) handshake: AES session key, no Noise transport
        assert client.crypto_key is not None
        assert client.noise_transport is None
        _assert_round_trip(client, m)
        client.close()
    finally:
        b.stop_all()


def test_v2_client_v3_server_uses_legacy_handshake():
    b, m = _master()
    try:
        b.start_all()
        client = _make_client(m.network_protocol.url, "matrix-key", "matrix-pwd",
                              max_protocol_version=2)
        client.connect(site_id="matrix-site")
        client.wait_for_handshake(timeout=10)
        assert client.crypto_key is not None
        assert client.noise_transport is None
        _assert_round_trip(client, m)
        client.close()
    finally:
        b.stop_all()


# ─────────────────────────────────────── authentication failures ──


def test_wrong_password_v3_handshake_fails_fast():
    b, m = _master(password="right-password")
    try:
        b.start_all()
        client = _make_client(m.network_protocol.url, "matrix-key",
                              "wrong-password")
        with pytest.raises(Exception):
            client.connect(site_id="matrix-site", handshake_max_retries=1)
        # PSK mismatch aborts cryptographically: no session of either kind,
        # and no silent fallback to the legacy handshake
        assert not client.handshake_event.is_set()
        assert client.noise_transport is None
        assert client.crypto_key is None
        assert not any("v3-matrix-client" in p for p in m.connected_peers())
        client.close()
    finally:
        b.stop_all()


def test_tampered_negotiation_aborts_handshake(monkeypatch):
    # simulate a MITM rewriting the server's advertised parameters (a
    # downgrade attempt): the client builds its Noise prologue from the
    # tampered payload, the server from what it actually sent — the
    # handshake transcripts disagree and the handshake MUST abort
    original = HiveMindSlaveProtocol.start_noise_handshake

    def tampered(self, server_payload):
        doctored = dict(server_payload)
        doctored["max_protocol_version"] = 3
        doctored["binarize"] = not doctored.get("binarize", False)
        return original(self, doctored)

    monkeypatch.setattr(HiveMindSlaveProtocol, "start_noise_handshake", tampered)

    b, m = _master()
    try:
        b.start_all()
        client = _make_client(m.network_protocol.url, "matrix-key", "matrix-pwd")
        with pytest.raises(Exception):
            client.connect(site_id="matrix-site", handshake_max_retries=1)
        assert not client.handshake_event.is_set()
        assert client.noise_transport is None
        assert not any("v3-matrix-client" in p for p in m.connected_peers())
        client.close()
    finally:
        b.stop_all()


# ────────────────────────────────────────────── replay resistance ──


def test_replayed_v3_transport_message_is_rejected():
    b, m = _master()
    try:
        b.start_all()
        client = _make_client(m.network_protocol.url, "matrix-key", "matrix-pwd")
        client.connect(site_id="matrix-site")
        client.wait_for_handshake(timeout=10)
        assert client.noise_transport is not None

        seen = []
        m.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)

        # capture the exact ciphertext of one legitimate transport message
        captured = []
        original_encrypt = client.noise_transport.encrypt_frame

        def capturing_encrypt(payload):
            ct = original_encrypt(payload)
            captured.append(ct)
            return ct

        client.noise_transport.encrypt_frame = capturing_encrypt
        client.emit(HiveMessage(
            HiveMessageType.BUS,
            payload=Message("recognizer_loop:utterance",
                            {"utterances": ["replay me"]}),
        ))
        assert _wait_for(lambda: len(seen) >= 1)
        assert captured, "no transport message captured"

        # replay the captured ciphertext verbatim on the raw websocket:
        # the server's receive nonce has moved on, AEAD fails, the message
        # is rejected and the server tears the session down (CRYPTO-1
        # §3.4.5). The client then auto-reconnects and completes a FRESH
        # handshake, so observe the teardown as a replaced Noise transport
        # (new CipherStates), not as a permanently absent peer.
        old_transport = client.noise_transport
        client.client.send(captured[0], ABNF.OPCODE_BINARY)

        assert _wait_for(
            lambda: client.noise_transport is not old_transport,
            timeout=15,
        ), "server did not tear down the session after a replayed message"
        time.sleep(0.5)
        assert len(seen) == 1, "replayed message was delivered twice"
        client.close()
    finally:
        b.stop_all()


# ──────────────────────────────────────── cached Noise PSK ──


def test_v3_handshake_derives_the_psk_once_across_reconnects():
    """The server derives one PSK for a password, then reuses it verbatim."""
    b, m = _master()
    try:
        b.start_all()
        with patch.object(server_protocol, "derive_psk",
                          wraps=server_protocol.derive_psk) as spy:
            for _ in range(3):
                client = _make_client(m.network_protocol.url,
                                      "matrix-key", "matrix-pwd")
                client.connect(site_id="matrix-site")
                client.wait_for_handshake(timeout=10)
                assert client.noise_transport is not None
                _assert_round_trip(client, m)
                client.close()
                assert _wait_for(lambda: not m.connected_peers())

        assert spy.call_count == 1, "the PSK was re-derived per connection"
    finally:
        b.stop_all()


def test_two_passwords_get_two_psks_and_both_handshakes_succeed():
    """The cache is keyed per password, so neither client gets the other's."""
    b = TopologyBuilder()
    m = b.add_master("M0", use_loopback=True)
    m.register_satellite("alice-key", password="alice-pwd",
                         allowed_types=["recognizer_loop:utterance"])
    m.register_satellite("bob-key", password="bob-pwd",
                         allowed_types=["recognizer_loop:utterance"])
    try:
        b.start_all()
        alice = _make_client(m.network_protocol.url, "alice-key", "alice-pwd",
                             name="alice")
        alice.connect(site_id="matrix-site")
        alice.wait_for_handshake(timeout=10)
        assert alice.noise_transport is not None

        bob = _make_client(m.network_protocol.url, "bob-key", "bob-pwd",
                           name="bob")
        bob.connect(site_id="matrix-site")
        bob.wait_for_handshake(timeout=10)
        assert bob.noise_transport is not None

        psks = list(m.hm_protocol._noise_psks.values())
        assert len(psks) == 2
        assert psks[0] != psks[1]

        # both sessions really work; round-trip one of them with the other
        # gone so _assert_round_trip addresses an unambiguous peer
        alice.close()
        assert _wait_for(lambda: len(m.connected_peers()) == 1)
        _assert_round_trip(bob, m)
        bob.close()
    finally:
        b.stop_all()
