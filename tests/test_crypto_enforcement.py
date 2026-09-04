"""Crypto enforcement at the protocol layer (HIVEMIND-CRYPTO-1).

The v3 Noise handshake is the sole transport crypto (§3.4), so every session
is encrypted and the enforcement paths are:

- crypto on receive (§4): a cleartext frame that is not HELLO/HANDSHAKE is
  rejected and the client dropped. HELLO/HANDSHAKE are always accepted in the
  clear (they precede the Noise session). A frame decrypted by the Noise
  transport is accepted.
- INTERCOM origin authentication (§5): signatures are verified against a
  TOFU-pinned public key (pin source = the pubkey presented in HELLO); a
  forged/mismatched signature after pinning is rejected; when no pubkey was
  ever presented, or no signature is carried, the origin cannot be
  authenticated and the message is rejected (fail closed). A rejected
  INTERCOM is dropped at this node: it is not relayed to peers and not
  escalated to the upstream master.
- Noise handshake abort (§3.4.3): every fatal handshake failure closes 1008,
  so a client retrying on a non-1008 close cannot spin forever on a wrong
  PSK, tampered negotiation, or a pinned-key contradiction.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

import pybase64
import pytest
from ovos_bus_client.message import Message
from poorman_handshake.asymmetric.utils import (create_RSA_key, encrypt_RSA,
                                                sign_RSA)

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol,
                                    UnencryptedMessageError)


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.callbacks = MagicMock()

    db_user = MagicMock()
    db_user.skill_blacklist = []
    db_user.intent_blacklist = []
    db_user.message_blacklist = []
    db_user.allowed_types = ["speak", "recognizer_loop:utterance"]
    db_user.is_admin = True

    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    return HiveMindListenerProtocol(agent_protocol=agent, db=db)


def _make_client(protocol, **kwargs):
    client = HiveMindClientConnection(
        key="test-key",
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=protocol,
        **kwargs,
    )
    client.name = "test-client"
    return client


def _cleartext_bus_frame():
    return HiveMessage(HiveMessageType.BUS,
                       payload=Message("speak", {"utterance": "hi"})).serialize()


class TestCryptoRequiredOnReceive(unittest.TestCase):
    """A v3 session is always encrypted: only HELLO/HANDSHAKE travel clear."""

    def test_cleartext_bus_rejected_before_handshake(self):
        proto = _make_protocol()
        client = _make_client(proto)  # no noise_transport yet
        with pytest.raises(UnencryptedMessageError):
            client.decode(_cleartext_bus_frame())
        client.disconnect.assert_called_once()

    def test_cleartext_hello_and_handshake_always_accepted(self):
        proto = _make_protocol()
        client = _make_client(proto)
        hello = HiveMessage(HiveMessageType.HELLO,
                            payload={"pubkey": "xxx"}).serialize()
        shake = HiveMessage(HiveMessageType.HANDSHAKE,
                            payload={"noise": {"msg": "yy"}}).serialize()
        assert client.decode(hello).msg_type == HiveMessageType.HELLO
        assert client.decode(shake).msg_type == HiveMessageType.HANDSHAKE
        client.disconnect.assert_not_called()

    def test_noise_transport_frame_accepted(self):
        proto = _make_protocol()
        client = _make_client(proto)
        client.noise_transport = MagicMock()
        client.noise_transport.decrypt_frame.return_value = _cleartext_bus_frame()
        msg = client.decode(b"noise-frame-bytes")
        assert msg.msg_type == HiveMessageType.BUS
        client.disconnect.assert_not_called()


class TestIntercomSignatureVerification(unittest.TestCase):
    """Fix for: INTERCOM end-to-end signatures never verified (origin forgery)."""

    @classmethod
    def setUpClass(cls):
        cls.server_pub, cls.server_priv = create_RSA_key()
        cls.client_pub, cls.client_priv = create_RSA_key()
        cls.forger_pub, cls.forger_priv = create_RSA_key()

    def setUp(self):
        self.proto = _make_protocol()
        import tempfile
        self._priv_file = tempfile.NamedTemporaryFile(
            "w", suffix=".pem", delete=False)
        self._priv_file.write(self.server_priv)
        self._priv_file.close()
        self.proto.identity = MagicMock()
        self.proto.identity.private_key = self._priv_file.name
        self.proto.identity.public_key = self.server_pub
        self.client = _make_client(self.proto)

    def tearDown(self):
        os.unlink(self._priv_file.name)

    def _intercom(self, sign_key):
        inner = HiveMessage(HiveMessageType.SHARED_BUS,
                            payload=Message("speak", {"utterance": "hi"}))
        ciphertext = encrypt_RSA(self.server_pub, inner.serialize())
        signature = sign_RSA(sign_key, ciphertext)
        return HiveMessage(
            HiveMessageType.INTERCOM,
            payload={"ciphertext": pybase64.b64encode(ciphertext).decode(),
                     "signature": pybase64.b64encode(signature).decode()})

    def test_valid_signature_accepted_and_pins_on_first_use(self):
        # pubkey presented in HELLO, nothing pinned yet
        self.client.pub_key = self.client_pub
        assert "test-key" not in self.proto.trusted_pubkeys
        assert self.proto.handle_intercom_message(
            self._intercom(self.client_priv), self.client) is True
        assert self.proto.trusted_pubkeys["test-key"] == self.client_pub

    def test_forged_signature_rejected_after_pinning(self):
        self.proto.trusted_pubkeys["test-key"] = self.client_pub
        self.proto.handle_client_shared_bus = MagicMock()
        # True == "consumed: dropped here", so callers stop relaying it
        assert self.proto.handle_intercom_message(
            self._intercom(self.forger_priv), self.client) is True
        self.proto.handle_client_shared_bus.assert_not_called()

    def test_pinned_key_wins_over_hello_key(self):
        # attacker re-HELLOs with its own pubkey but the pin is authoritative
        self.proto.trusted_pubkeys["test-key"] = self.client_pub
        self.client.pub_key = self.forger_pub
        assert self.proto.handle_intercom_message(
            self._intercom(self.forger_priv), self.client) is True

    def test_no_pubkey_rejects_unverifiable_origin(self):
        # peer never presented a pubkey: origin cannot be authenticated,
        # fail closed and drop rather than dispatch unverified (CRYPTO-1 §5)
        self.client.pub_key = None
        with patch("hivemind_core.protocol.LOG") as mock_log:
            assert self.proto.handle_intercom_message(
                self._intercom(self.forger_priv), self.client) is True
        assert mock_log.warning.called
        assert self.client.peer in mock_log.warning.call_args[0][0]

    def test_missing_signature_rejected_even_with_pinned_key(self):
        # pubkey is pinned, but the frame carries no signature at all:
        # nothing to verify against, drop rather than trust blindly
        self.proto.trusted_pubkeys["test-key"] = self.client_pub
        frame = self._intercom(self.client_priv)
        frame.payload.pop("signature")
        with patch("hivemind_core.protocol.LOG") as mock_log:
            assert self.proto.handle_intercom_message(frame, self.client) is True
        assert mock_log.warning.called
        assert "no signature" in mock_log.warning.call_args[0][0]

    def test_hello_pins_pubkey_and_keeps_first_pin(self):
        hello = HiveMessage(HiveMessageType.HELLO,
                            payload={"pubkey": self.client_pub})
        self.client.is_admin = True
        self.proto.handle_hello_message(hello, self.client)
        assert self.proto.trusted_pubkeys["test-key"] == self.client_pub
        # a later HELLO with a different key must not overwrite the pin
        hello2 = HiveMessage(HiveMessageType.HELLO,
                             payload={"pubkey": self.forger_pub})
        self.proto.handle_hello_message(hello2, self.client)
        assert self.proto.trusted_pubkeys["test-key"] == self.client_pub


class TestRejectedIntercomIsNotRelayed(unittest.TestCase):
    """A refused INTERCOM must be dropped, never fanned out or escalated.

    ``handle_intercom_message`` returning False means "not addressed to me,
    keep relaying"; every caller does ``if handle_intercom_message(...):
    return``. So an authentication failure has to be reported as consumed
    (True), otherwise rejecting a frame would *amplify* it to every peer and
    to the upstream master.
    """

    @classmethod
    def setUpClass(cls):
        cls.server_pub, cls.server_priv = create_RSA_key()
        cls.client_pub, cls.client_priv = create_RSA_key()
        cls.forger_pub, cls.forger_priv = create_RSA_key()

    def setUp(self):
        import tempfile
        self.proto = _make_protocol()
        self._priv_file = tempfile.NamedTemporaryFile(
            "w", suffix=".pem", delete=False)
        self._priv_file.write(self.server_priv)
        self._priv_file.close()
        self.proto.identity = MagicMock()
        self.proto.identity.private_key = self._priv_file.name
        self.proto.identity.public_key = self.server_pub
        self.proto._upstream_hm = MagicMock()

        self.client = _make_client(self.proto)
        # pinned pubkey, but the frame will be signed by the forger
        self.proto.trusted_pubkeys["test-key"] = self.client_pub

        self.peer = MagicMock()
        self.proto.clients["peer-1"] = self.peer

    def tearDown(self):
        os.unlink(self._priv_file.name)

    def _forged_intercom(self):
        inner = HiveMessage(HiveMessageType.SHARED_BUS,
                            payload=Message("speak", {"utterance": "hi"}))
        ciphertext = encrypt_RSA(self.server_pub, inner.serialize())
        signature = sign_RSA(self.forger_priv, ciphertext)
        return HiveMessage(
            HiveMessageType.INTERCOM,
            payload={"ciphertext": pybase64.b64encode(ciphertext).decode(),
                     "signature": pybase64.b64encode(signature).decode()})

    def _assert_dropped(self):
        self.peer.send.assert_not_called()
        self.proto._upstream_hm.emit.assert_not_called()

    def test_rejected_intercom_not_broadcast_to_peers(self):
        self.client.is_admin = True
        self.proto.handle_broadcast_message(
            HiveMessage(HiveMessageType.BROADCAST,
                        payload=self._forged_intercom()), self.client)
        self._assert_dropped()

    def test_rejected_intercom_not_propagated_to_peers_or_master(self):
        self.client.can_propagate = True
        self.proto.handle_propagate_message(
            HiveMessage(HiveMessageType.PROPAGATE,
                        payload=self._forged_intercom()), self.client)
        self._assert_dropped()

    def test_rejected_intercom_not_escalated_to_master(self):
        self.client.can_escalate = True
        self.proto.handle_escalate_message(
            HiveMessage(HiveMessageType.ESCALATE,
                        payload=self._forged_intercom()), self.client)
        self._assert_dropped()


class TestNoiseHandshakeAbortCloseCode(unittest.TestCase):
    """Fix for: handshake-time auth/credential rejections closed with a bare
    (code 1000) close, so a client retrying on any non-1008 close would spin
    forever on a wrong PSK, tampered negotiation, or a pinned-key
    contradiction. ``_abort_noise_handshake`` is the single fatal exit for
    all of those, so it must always close 1008.
    """

    def test_abort_closes_1008(self):
        proto = _make_protocol()
        client = _make_client(proto)
        proto.handle_invalid_key_connected = MagicMock()
        proto._abort_noise_handshake(client, "wrong PSK")
        client.disconnect.assert_called_once()
        assert client.disconnect.call_args.args == (1008, "wrong PSK")


if __name__ == "__main__":
    unittest.main()
