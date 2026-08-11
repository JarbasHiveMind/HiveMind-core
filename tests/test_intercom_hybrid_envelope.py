"""INTERCOM addressed to the hub must decrypt (HIVEMIND-CRYPTO-1 §5).

``HiveMessageBusClient.emit_intercom`` produces a **hybrid** envelope: a random
AES-256-GCM key encrypts the payload and RSA encrypts only that key, because raw
RSA cannot carry more than one block. hivemind-core used to RSA-decrypt the
``ciphertext`` field directly and never looked at ``encrypted_key``, so every
INTERCOM a client addressed to the hub failed to decrypt and was dropped.

Peer-to-peer INTERCOM was never affected: core relays a frame addressed to
someone else without opening it.

Both envelope shapes are pinned here. The plain-RSA shape stays accepted so an
existing peer that speaks it keeps working.
"""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pybase64
from Cryptodome.PublicKey import RSA
from hivemind_bus_client.encryption import hybrid_encrypt
from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message
from poorman_handshake.asymmetric.utils import encrypt_RSA, sign_RSA

from hivemind_core.protocol import HiveMindListenerProtocol


def _keypair():
    key = RSA.generate(2048)
    return key, key.publickey().export_key().decode("utf-8")


def _node(node_key, node_pub, client_pub, tmp_path=None):
    """A listener that owns *node_key* and has already pinned *client_pub*.

    ``identity.private_key`` is a **path** — ``load_RSA_key`` opens it — so the
    key is written out rather than passed as PEM text.
    """
    node = object.__new__(HiveMindListenerProtocol)
    keyfile = Path(tempfile.mkdtemp()) / "node.key"
    keyfile.write_bytes(node_key.export_key())
    node.identity = MagicMock(
        private_key=str(keyfile),
        public_key=node_pub,
        site_id=None,
    )
    node.clients = {}
    node.agent_protocol = MagicMock()
    node.require_crypto = True
    node.trusted_pubkeys = {"client-key": client_pub}
    # a permissive chain: this module is about the crypto path, and admission
    # is covered by the policy tests
    node.policy_chain = MagicMock()
    node.policy_chain.review.return_value = MagicMock(denied=False, mutations=[])
    return node


def _capture(node):
    """Record what the node dispatches after decrypting."""
    seen = []
    node.handle_bus_message = lambda inner, client: seen.append(inner)
    return seen


def _client():
    c = MagicMock()
    c.key = "client-key"
    c.peer = "sat::1"
    return c


def _inner():
    return HiveMessage(HiveMessageType.BUS,
                       payload=Message("recognizer_loop:utterance",
                                       {"utterances": ["hello from intercom"]}))


class TestHybridEnvelope:
    """The shape the reference client actually sends."""

    def test_a_hybrid_intercom_addressed_to_us_is_decrypted_and_dispatched(self):
        node_key, node_pub = _keypair()
        sender_key, sender_pub = _keypair()
        node = _node(node_key, node_pub, sender_pub)
        dispatched = _capture(node)

        envelope = hybrid_encrypt(node_pub, _inner().serialize(), sign_key=sender_key)
        msg = HiveMessage(HiveMessageType.INTERCOM, payload=envelope,
                          target_pubkey=node_pub)

        consumed = node.handle_intercom_message(msg, _client())

        assert consumed is True, "a frame addressed to us is consumed, not relayed"
        # The decisive assertion: it decrypted and was dispatched, not dropped.
        assert dispatched, "hybrid INTERCOM was not decrypted and dispatched"
        assert dispatched[0].msg_type == HiveMessageType.BUS
        assert dispatched[0].payload.data["utterances"] == ["hello from intercom"]

    def test_a_payload_larger_than_one_rsa_block_survives(self):
        """The reason hybrid exists. Raw RSA caps at ~214 bytes with a
        2048-bit key, which a real utterance envelope exceeds."""
        node_key, node_pub = _keypair()
        sender_key, sender_pub = _keypair()
        node = _node(node_key, node_pub, sender_pub)
        dispatched = _capture(node)

        big = HiveMessage(HiveMessageType.BUS,
                          payload=Message("recognizer_loop:utterance",
                                          {"utterances": ["x" * 2000]}))
        assert len(big.serialize()) > 214

        envelope = hybrid_encrypt(node_pub, big.serialize(), sign_key=sender_key)
        msg = HiveMessage(HiveMessageType.INTERCOM, payload=envelope,
                          target_pubkey=node_pub)

        assert node.handle_intercom_message(msg, _client()) is True
        assert dispatched, "plain-RSA INTERCOM must still be accepted"


class TestPlainRsaEnvelopeStillAccepted:
    """Back-compat: a peer that speaks the older shape keeps working."""

    def test_a_plain_rsa_intercom_is_still_decrypted(self):
        node_key, node_pub = _keypair()
        sender_key, sender_pub = _keypair()
        node = _node(node_key, node_pub, sender_pub)
        dispatched = _capture(node)

        # small enough to fit one RSA block
        inner = HiveMessage(HiveMessageType.BUS, payload=Message("ping"))
        body = inner.serialize().encode("utf-8")
        assert len(body) < 214

        ciphertext = encrypt_RSA(node_pub, body)
        envelope = {
            "ciphertext": pybase64.b64encode(ciphertext).decode("ascii"),
            "signature": pybase64.b64encode(sign_RSA(sender_key, ciphertext)).decode("ascii"),
        }
        msg = HiveMessage(HiveMessageType.INTERCOM, payload=envelope,
                          target_pubkey=node_pub)

        assert node.handle_intercom_message(msg, _client()) is True
        assert dispatched, "plain-RSA INTERCOM must still be accepted"


class TestOriginStillAuthenticated:
    """The fix must not weaken CRYPTO-1 §5."""

    def test_a_hybrid_envelope_signed_by_the_wrong_key_is_dropped(self):
        node_key, node_pub = _keypair()
        _, pinned_pub = _keypair()
        forger_key, _ = _keypair()
        node = _node(node_key, node_pub, pinned_pub)
        dispatched = _capture(node)

        envelope = hybrid_encrypt(node_pub, _inner().serialize(), sign_key=forger_key)
        msg = HiveMessage(HiveMessageType.INTERCOM, payload=envelope,
                          target_pubkey=node_pub)

        assert node.handle_intercom_message(msg, _client()) is True
        assert not dispatched, "an unverifiable origin must be dropped"

    def test_an_unsigned_hybrid_envelope_is_dropped(self):
        node_key, node_pub = _keypair()
        _, sender_pub = _keypair()
        node = _node(node_key, node_pub, sender_pub)
        dispatched = _capture(node)

        envelope = hybrid_encrypt(node_pub, _inner().serialize())  # no sign_key
        msg = HiveMessage(HiveMessageType.INTERCOM, payload=envelope,
                          target_pubkey=node_pub)

        assert node.handle_intercom_message(msg, _client()) is True
        assert not dispatched, "an unverifiable origin must be dropped"
