"""The v3 Noise handshake is the sole transport crypto (HIVEMIND-CRYPTO-1 §3.4).

There is no legacy (v1/v2) fallback: a connection that cannot complete the
Noise handshake is rejected with 1008, the HELLO/HANDSHAKE parameters advertise
only what Noise needs, ``add-client`` has no ``--crypto-key`` option, and no
AES pre-shared-key transport path remains in the protocol module.
"""
import pathlib
import unittest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)
from hivemind_core.scripts import add_client, derive_psk


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.callbacks = MagicMock()
    db_user = MagicMock()
    db_user.allowed_types = ["speak"]
    db_user.is_admin = True
    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user
    return HiveMindListenerProtocol(agent_protocol=agent, db=db)


def _make_client(protocol, **kwargs):
    client = HiveMindClientConnection(
        key="test-key", send_msg=MagicMock(), disconnect=MagicMock(),
        hm_protocol=protocol, **kwargs)
    client.name = "test-client"
    return client


class TestSubV3Rejected(unittest.TestCase):
    """A connection that cannot do the Noise handshake gets no legacy fallback.

    FAIL-BEFORE: before the flag-day the server negotiated a v1/v2 handshake
    for such a client instead of rejecting it, so no 1008 close was issued.
    """

    def test_no_password_connection_rejected_1008(self):
        proto = _make_protocol()
        client = _make_client(proto, pswd_handshake=None)  # not v3-capable
        with patch("hivemind_core.protocol.NOISE_SUPPORTED", True):
            proto.handle_new_client(client)
        client.disconnect.assert_called_once()
        assert client.disconnect.call_args.args[0] == 1008
        # nothing was offered to the client: no HELLO/HANDSHAKE went out
        client.send_msg.assert_not_called()

    def test_noise_unavailable_connection_rejected_1008(self):
        proto = _make_protocol()
        client = _make_client(proto, pswd_handshake=MagicMock())
        with patch("hivemind_core.protocol.NOISE_SUPPORTED", False):
            proto.handle_new_client(client)
        client.disconnect.assert_called_once()
        assert client.disconnect.call_args.args[0] == 1008

    def test_legacy_handshake_frame_rejected_1008(self):
        # a client that answers HELLO with a legacy (non-noise) handshake is
        # aborted, never handed a legacy key
        proto = _make_protocol()
        client = _make_client(proto, pswd_handshake=MagicMock())
        proto.handle_invalid_key_connected = MagicMock()
        legacy = HiveMessage(HiveMessageType.HANDSHAKE,
                             payload={"envelope": "legacy-v2-envelope"})
        proto.handle_handshake_message(legacy, client)
        client.disconnect.assert_called_once()
        assert client.disconnect.call_args.args[0] == 1008


class TestHandshakeParamsAreNoiseOnly(unittest.TestCase):
    """HELLO/HANDSHAKE advertise only what the Noise handshake needs."""

    def test_no_legacy_crypto_fields_advertised(self):
        proto = _make_protocol()
        client = _make_client(proto, pswd_handshake=MagicMock(),
                              handshake=MagicMock(pubkey="PUB"))
        sent = []
        client.send = lambda msg, plaintext=None: sent.append(msg)
        with patch("hivemind_core.protocol.NOISE_SUPPORTED", True):
            proto.handle_new_client(client)

        handshakes = [m.payload for m in sent
                      if m.msg_type == HiveMessageType.HANDSHAKE]
        assert handshakes, "no HANDSHAKE emitted"
        payload = handshakes[-1]
        # the only transport crypto is Noise
        assert "noise" in payload
        for legacy in ("preshared_key", "password", "crypto_required",
                       "handshake"):
            assert legacy not in payload, f"legacy field {legacy!r} still advertised"

        hellos = [m.payload for m in sent if m.msg_type == HiveMessageType.HELLO]
        assert hellos and "crypto_key" not in hellos[-1]

    def test_protocol_version_advertised_for_noise_selection(self):
        # a v3 client's HiveMindSlaveProtocol._should_use_noise() requires
        # max_protocol_version >= 3 in this payload to select the Noise path
        proto = _make_protocol()
        client = _make_client(proto, pswd_handshake=MagicMock(),
                              handshake=MagicMock(pubkey="PUB"))
        sent = []
        client.send = lambda msg, plaintext=None: sent.append(msg)
        with patch("hivemind_core.protocol.NOISE_SUPPORTED", True):
            proto.handle_new_client(client)

        handshakes = [m.payload for m in sent
                      if m.msg_type == HiveMessageType.HANDSHAKE]
        assert handshakes, "no HANDSHAKE emitted"
        payload = handshakes[-1]
        assert payload["max_protocol_version"] == 3
        assert "min_protocol_version" not in payload


class TestDuplicateHandshakeAfterEstablished(unittest.TestCase):
    """A fresh, well-formed HANDSHAKE frame arriving after the Noise
    session is established must be rejected, not treated as a new message 1.

    FAIL-BEFORE: without the guard, such a frame re-enters the
    ``client.noise_handshake is None`` branch (true post-establishment,
    since a successful handshake sets it back to None), passes the
    offered-pattern/suite check (the offer is still sitting on
    ``client._handshake_payload``), and builds a brand new responder
    handshake object and message 2 — silently RESETTING the established
    session instead of crashing or rejecting. That is a handshake-reset/
    confusion vector: a client-controlled frame overwrites live session
    state after authentication already completed.
    """

    def _make_established_client(self, proto):
        client = _make_client(proto, pswd_handshake=MagicMock(password="secret"))
        # Simulate a completed Noise handshake: the offer is still on
        # _handshake_payload (never cleared), noise_handshake is back to
        # None, and noise_transport now holds the live session.
        client._handshake_payload = {
            "noise": {"patterns": ["XXpsk2"],
                      "suites": ["25519_ChaChaPoly_BLAKE2s"]}}
        client._hello_payload = {}
        client.noise_handshake = None
        client.noise_transport = MagicMock(name="established-transport")
        client.send = MagicMock()
        return client

    def test_post_established_handshake_frame_rejected_not_reset(self):
        proto = _make_protocol()
        client = self._make_established_client(proto)
        established_transport = client.noise_transport

        message = HiveMessage(
            HiveMessageType.HANDSHAKE,
            {"noise": {"pattern": "XXpsk2", "suite": "25519_ChaChaPoly_BLAKE2s",
                       "msg": "00"}})

        fake_new_handshake = MagicMock(name="new-responder-handshake")
        fake_new_handshake.read_message.return_value = b"{}"
        fake_new_handshake.write_message.return_value = b"new-msg2-bytes"
        # XXpsk2 mid-flight after message 1/2: waiting for message 3, exactly
        # like the real first handshake once was -- so the reset stops here,
        # at "msg2 already sent", without needing a full second Noise session.
        fake_new_handshake.handshake_finished = False
        with patch("hivemind_core.protocol.NOISE_SUPPORTED", True), \
             patch("hivemind_core.protocol.start_noise_handshake",
                   return_value=fake_new_handshake) as start_mock:
            proto.handle_noise_handshake_message(message, client)

        # rejected, not silently re-handshaked
        client.disconnect.assert_called_with(1008, unittest.mock.ANY)
        # no new responder handshake was started
        start_mock.assert_not_called()
        # the established transport was torn down by the abort path (fatal
        # per _abort_noise_handshake), never silently replaced in place
        self.assertIsNone(client.noise_handshake)
        self.assertIsNot(client.noise_transport, fake_new_handshake)
        # no message 2 (or any other reply) was sent for this frame
        client.send.assert_not_called()



class TestAddClientHasNoCryptoKey(unittest.TestCase):
    def test_crypto_key_option_removed(self):
        result = CliRunner().invoke(add_client, [
            "--access-key", "x", "--crypto-key", "0123456789abcdef"])
        assert result.exit_code != 0
        assert "no such option" in result.output.lower()

    def test_derive_psk_still_works(self):
        result = CliRunner().invoke(derive_psk, [
            "--password", "correct-horse-battery-staple-92",
            "--node-id", "some-node-id"])
        assert result.exit_code == 0, result.output
        # a hex-encoded 32-byte PSK
        assert len(result.output.strip()) == 64


def test_no_legacy_transport_crypto_symbols_in_protocol():
    """Grep guard: the AES pre-shared-key transport path is gone."""
    src = (pathlib.Path(__file__).parent.parent
           / "hivemind_core" / "protocol.py").read_text()
    for symbol in ("encrypt_bin", "decrypt_bin", "crypto_key",
                   "encrypt_as_json", "decrypt_from_json"):
        assert symbol not in src, f"legacy transport-crypto symbol {symbol!r} remains"


if __name__ == "__main__":
    unittest.main()
