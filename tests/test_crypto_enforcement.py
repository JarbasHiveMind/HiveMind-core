"""Crypto enforcement at the protocol layer (HIVEMIND-CRYPTO-1).

Covers the additive, wire-compatible enforcement paths:

- ``crypto_required`` on receive (§4): a crypto-required server rejects any
  cleartext frame that is not HELLO/HANDSHAKE and drops the client; a
  non-required server keeps accepting cleartext; HELLO/HANDSHAKE are always
  accepted in the clear (they precede key establishment). Encrypted frames
  are unaffected.
- INTERCOM origin authentication (§5): signatures are verified against a
  TOFU-pinned public key (pin source = the pubkey presented in HELLO); a
  forged/mismatched signature after pinning is rejected; when no pubkey was
  ever presented the message is still processed (permissive fallback) but
  origin authenticity is unverified.
- Password handshake fail-fast (§3.2): a client envelope built with the
  wrong password is rejected at handshake time instead of only failing to
  decrypt the first encrypted frame.
"""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

import pybase64
import pytest
from ovos_bus_client.message import Message
from poorman_handshake import PasswordHandShake
from poorman_handshake.asymmetric.utils import (create_RSA_key, encrypt_RSA,
                                                sign_RSA)

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_bus_client.encryption import (SupportedCiphers,
                                            SupportedEncodings,
                                            encrypt_as_json)
from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol,
                                    UnencryptedMessageError)


def _make_protocol(require_crypto=True):
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

    return HiveMindListenerProtocol(agent_protocol=agent, db=db,
                                    require_crypto=require_crypto)


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
    """Fix for: crypto_required advertised but not enforced on inbound frames."""

    def test_cleartext_bus_rejected_when_crypto_required_post_handshake(self):
        proto = _make_protocol(require_crypto=True)
        client = _make_client(proto)
        client.crypto_key = os.urandom(32)  # handshake done
        with pytest.raises(UnencryptedMessageError):
            client.decode(_cleartext_bus_frame())
        client.disconnect.assert_called_once()

    def test_cleartext_bus_rejected_when_crypto_required_pre_handshake(self):
        proto = _make_protocol(require_crypto=True)
        client = _make_client(proto)  # no crypto_key yet
        with pytest.raises(UnencryptedMessageError):
            client.decode(_cleartext_bus_frame())
        client.disconnect.assert_called_once()

    def test_cleartext_hello_and_handshake_always_accepted(self):
        proto = _make_protocol(require_crypto=True)
        client = _make_client(proto)
        hello = HiveMessage(HiveMessageType.HELLO,
                            payload={"pubkey": "xxx"}).serialize()
        shake = HiveMessage(HiveMessageType.HANDSHAKE,
                            payload={"envelope": "yyy"}).serialize()
        assert client.decode(hello).msg_type == HiveMessageType.HELLO
        assert client.decode(shake).msg_type == HiveMessageType.HANDSHAKE
        client.disconnect.assert_not_called()

    def test_cleartext_bus_accepted_when_crypto_not_required(self):
        proto = _make_protocol(require_crypto=False)
        client = _make_client(proto)
        msg = client.decode(_cleartext_bus_frame())
        assert msg.msg_type == HiveMessageType.BUS
        client.disconnect.assert_not_called()

    def test_cleartext_bus_accepted_without_listener_protocol(self):
        # connection not attached to a listener: keep permissive behavior
        client = HiveMindClientConnection(key="k", send_msg=MagicMock(),
                                          disconnect=MagicMock(),
                                          handshake=MagicMock())
        msg = client.decode(_cleartext_bus_frame())
        assert msg.msg_type == HiveMessageType.BUS

    def test_encrypted_bus_accepted_when_crypto_required(self):
        proto = _make_protocol(require_crypto=True)
        client = _make_client(proto)
        client.crypto_key = os.urandom(32)
        ciphertext = encrypt_as_json(key=client.crypto_key,
                                     plaintext=_cleartext_bus_frame(),
                                     cipher=SupportedCiphers.AES_GCM,
                                     encoding=SupportedEncodings.JSON_HEX)
        msg = client.decode(ciphertext)
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
        assert self.proto.handle_intercom_message(
            self._intercom(self.forger_priv), self.client) is False

    def test_pinned_key_wins_over_hello_key(self):
        # attacker re-HELLOs with its own pubkey but the pin is authoritative
        self.proto.trusted_pubkeys["test-key"] = self.client_pub
        self.client.pub_key = self.forger_pub
        assert self.proto.handle_intercom_message(
            self._intercom(self.forger_priv), self.client) is False

    def test_no_pubkey_falls_back_to_unverified_processing(self):
        # peer never presented a pubkey: keep permissive (additive) behavior
        self.client.pub_key = None
        assert self.proto.handle_intercom_message(
            self._intercom(self.forger_priv), self.client) is True

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


class TestPasswordHandshakeFailFast(unittest.TestCase):
    """Fix for: wrong password only failed via implicit key-confirmation."""

    # High-entropy passphrases: poorman_handshake>=2.0 rejects weak passwords
    # in PasswordHandShake, so these tests (which target handshake verification,
    # not password strength) use secrets that clear the strength floor.
    _RIGHT_PASSWORD = "correct-horse-battery-staple-92"
    _WRONG_PASSWORD = "totally-different-quokka-melody-47"

    def _handshake_msg(self, password):
        peer_side = PasswordHandShake(password)
        return HiveMessage(HiveMessageType.HANDSHAKE,
                           payload={"envelope": peer_side.generate_handshake()})

    def test_correct_password_handshake_succeeds(self):
        proto = _make_protocol()
        client = _make_client(proto)
        client.pswd_handshake = PasswordHandShake(self._RIGHT_PASSWORD)
        proto.handle_handshake_message(self._handshake_msg(self._RIGHT_PASSWORD), client)
        assert client.crypto_key is not None
        client.disconnect.assert_not_called()
        # HANDSHAKE reply with our envelope was sent back
        client.send_msg.assert_called_once()
        reply = json.loads(client.send_msg.call_args[0][0])
        assert reply["msg_type"] == HiveMessageType.HANDSHAKE
        assert "envelope" in reply["payload"]

    def test_wrong_password_rejected_at_handshake_time(self):
        proto = _make_protocol()
        client = _make_client(proto)
        client.pswd_handshake = PasswordHandShake(self._RIGHT_PASSWORD)
        proto.handle_handshake_message(self._handshake_msg(self._WRONG_PASSWORD), client)
        assert client.crypto_key is None
        client.disconnect.assert_called_once()
        client.send_msg.assert_not_called()

    def test_garbage_envelope_rejected_at_handshake_time(self):
        proto = _make_protocol()
        client = _make_client(proto)
        client.pswd_handshake = PasswordHandShake(self._RIGHT_PASSWORD)
        msg = HiveMessage(HiveMessageType.HANDSHAKE,
                          payload={"envelope": "not-a-real-envelope"})
        proto.handle_handshake_message(msg, client)
        assert client.crypto_key is None
        client.disconnect.assert_called_once()


class TestMinProtocolVersionFloor(unittest.TestCase):
    """Fix for: min_protocol_version was advisory only.

    A hub configured with a raised floor (e.g. 3, Noise-required) must
    reject a client that completes a legacy v2 password handshake instead
    of Noise, even though that same client is v3-*capable* (has a
    pswd_handshake) and so was never caught by the min>max check done at
    HELLO time. HIVEMIND-CRYPTO-1's floor is fail-closed: the hub MUST NOT
    let a connection settle below the configured minimum.
    """

    _PASSWORD = "correct-horse-battery-staple-92"

    def _handshake_msg(self):
        peer_side = PasswordHandShake(self._PASSWORD)
        return HiveMessage(HiveMessageType.HANDSHAKE,
                           payload={"envelope": peer_side.generate_handshake()})

    def test_v2_password_handshake_rejected_when_floor_is_3(self):
        proto = _make_protocol()
        client = _make_client(proto)
        client.pswd_handshake = PasswordHandShake(self._PASSWORD)
        with patch("hivemind_core.protocol.get_server_config",
                  return_value={"min_protocol_version": 3}):
            proto.handle_handshake_message(self._handshake_msg(), client)
        assert client.crypto_key is None
        client.disconnect.assert_called_once()
        client.send_msg.assert_not_called()

    def test_v2_password_handshake_accepted_when_floor_is_2(self):
        proto = _make_protocol()
        client = _make_client(proto)
        client.pswd_handshake = PasswordHandShake(self._PASSWORD)
        with patch("hivemind_core.protocol.get_server_config",
                  return_value={"min_protocol_version": 2}):
            proto.handle_handshake_message(self._handshake_msg(), client)
        assert client.crypto_key is not None
        client.disconnect.assert_not_called()
        client.send_msg.assert_called_once()


if __name__ == "__main__":
    unittest.main()
