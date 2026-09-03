"""The handshake decision must key on the negotiated connection capability,
never on a provisioned ``crypto_key`` (HIVEMIND-CRYPTO-1, transport downgrade).

A v3-capable connection is one whose client presented a password, so
``pswd_handshake`` is set and the Noise handshake is available. Such a
connection must always run the handshake when it is enabled, even if the DB row
still carries a legacy ``crypto_key`` column: a provisioning artifact must not
downgrade the transport to the v2 AES path (the stray key is cleared
post-handshake). A connection that is not v3-capable keeps using the legacy
crypto_key path its handshake actually negotiates.

The observable contract is the ``handshake`` field of the HANDSHAKE payload the
server emits during ``handle_new_client``.
"""

import unittest
from unittest.mock import MagicMock, patch

from hivemind_bus_client import HiveMessageType
from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol, ProtocolVersion)


def _make_protocol(handshake_enabled=True):
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

    protocol = HiveMindListenerProtocol(agent_protocol=agent, db=db,
                                        require_crypto=False)
    protocol.handshake_enabled = handshake_enabled
    return protocol


def _make_client(protocol, pswd_handshake, crypto_key):
    client = HiveMindClientConnection(
        key="test-key",
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=protocol,
    )
    client.name = "test-client"
    client.pswd_handshake = pswd_handshake
    client.crypto_key = crypto_key
    return client


def _handshake_flag(protocol, client, noise_supported=True):
    """Run handle_new_client and return the ``handshake`` field the server
    advertised in the emitted HANDSHAKE payload."""
    sent = []
    client.send = lambda msg, plaintext=None: sent.append(msg)
    # Keep version negotiation from rejecting the legacy (v1) connection before
    # HANDSHAKE is emitted; the handshake decision under test is independent of
    # the configured floor.
    with patch("hivemind_core.protocol.NOISE_SUPPORTED", noise_supported), \
         patch("hivemind_core.protocol._configured_min_protocol_version",
               return_value=ProtocolVersion.ZERO):
        protocol.handle_new_client(client)
    handshakes = [m.payload for m in sent
                  if m.msg_type == HiveMessageType.HANDSHAKE]
    assert handshakes, "no HANDSHAKE message was emitted"
    return handshakes[-1]["handshake"]


class TestHandshakeNotDowngradedByCryptoKey(unittest.TestCase):
    def test_v3_capable_with_stray_crypto_key_still_handshakes(self):
        # THE DOWNGRADE CASE: password present (v3-capable) AND a lingering
        # provisioned crypto_key. The stray key must NOT suppress the handshake.
        protocol = _make_protocol(handshake_enabled=True)
        client = _make_client(protocol, pswd_handshake=MagicMock(),
                              crypto_key="provisioned-legacy-key")
        self.assertTrue(_handshake_flag(protocol, client))

    def test_v3_capable_no_crypto_key_handshakes(self):
        protocol = _make_protocol(handshake_enabled=True)
        client = _make_client(protocol, pswd_handshake=MagicMock(),
                              crypto_key=None)
        self.assertTrue(_handshake_flag(protocol, client))

    def test_not_v3_capable_with_crypto_key_uses_legacy_path(self):
        # No password -> not v3-capable -> the legacy crypto_key AES path its
        # connection actually negotiates is preserved (no handshake requested).
        protocol = _make_protocol(handshake_enabled=True)
        client = _make_client(protocol, pswd_handshake=None,
                              crypto_key="legacy-shared-key")
        self.assertFalse(_handshake_flag(protocol, client))

    def test_handshake_disabled_never_handshakes(self):
        protocol = _make_protocol(handshake_enabled=False)
        client = _make_client(protocol, pswd_handshake=MagicMock(),
                              crypto_key=None)
        self.assertFalse(_handshake_flag(protocol, client))


if __name__ == "__main__":
    unittest.main()
