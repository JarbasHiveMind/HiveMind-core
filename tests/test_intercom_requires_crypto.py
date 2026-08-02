"""Unauthenticated INTERCOM must be refused when the hub requires crypto.

``handle_intercom_message`` verifies the origin RSA signature (CRYPTO-1 §5)
only on the signed-envelope branch (``{"ciphertext": ...}``). The two sibling
branches — an inner ``HiveMessage`` payload, and a plain dict payload — used
to dispatch the inner message to the bus with no origin authentication at
all, so omitting the ``ciphertext`` field walked straight past the §5 check.

A hub with ``require_crypto=True`` advertises ``crypto_required`` to clients
and means "unencrypted payloads are not allowed". These tests hold it to
that: the unauthenticated branches are dropped (and, being dropped, are not
relayed to peers or escalated upstream). With ``require_crypto=False`` the
deliberate plaintext INTERCOM feature (issue #117 / PR #123) still works.
"""

import tempfile
import unittest
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from poorman_handshake.asymmetric.utils import create_RSA_key

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)


def _make_protocol(require_crypto):
    agent = MagicMock()
    agent.bus = MagicMock()
    db = MagicMock()
    return HiveMindListenerProtocol(agent_protocol=agent, db=db,
                                    require_crypto=require_crypto)


def _real_key_identity(pubkey, privkey_pem):
    """Identity backed by a real RSA key file.

    ``HiveMindClientConnection`` builds an RSA HandShake from
    ``identity.private_key`` on construction, so it must be a usable key path.
    """
    handle = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
    handle.write(privkey_pem)
    handle.close()
    identity = MagicMock()
    identity.private_key = handle.name
    identity.public_key = pubkey
    return identity


def _make_client(protocol):
    client = HiveMindClientConnection(
        key="test-key",
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=protocol,
    )
    client.name = "test-client"
    return client


def _inner_bus():
    return HiveMessage(HiveMessageType.BUS,
                       payload=Message("speak", {"utterance": "hi"}))


class TestUnauthenticatedIntercomRefused(unittest.TestCase):
    """require_crypto=True: no signature, no delivery, no relay."""

    @classmethod
    def setUpClass(cls):
        cls.server_pub, cls.server_priv = create_RSA_key()

    def setUp(self):
        self.proto = _make_protocol(require_crypto=True)
        self.proto.identity = _real_key_identity(self.server_pub, self.server_priv)
        self.proto.handle_bus_message = MagicMock()
        self.proto._upstream_hm = MagicMock()
        self.client = _make_client(self.proto)
        self.peer = MagicMock()
        self.proto.clients["peer-1"] = self.peer

    def _assert_dropped(self, handled, mock_log):
        # consumed here: callers must not relay or escalate it
        assert handled is True
        self.proto.handle_bus_message.assert_not_called()
        self.peer.send.assert_not_called()
        self.proto._upstream_hm.emit.assert_not_called()
        assert mock_log.warning.called
        assert self.client.peer in mock_log.warning.call_args[0][0]

    def test_plaintext_dict_intercom_is_dropped(self):
        frame = HiveMessage(HiveMessageType.INTERCOM,
                            payload=_inner_bus().serialize())
        with patch("hivemind_core.protocol.LOG") as mock_log:
            handled = self.proto.handle_intercom_message(frame, self.client)
        self._assert_dropped(handled, mock_log)

    def test_hivemessage_payload_intercom_is_dropped(self):
        frame = HiveMessage(HiveMessageType.INTERCOM, payload=_inner_bus())
        with patch("hivemind_core.protocol.LOG") as mock_log:
            handled = self.proto.handle_intercom_message(frame, self.client)
        self._assert_dropped(handled, mock_log)


class TestPlaintextIntercomStillWorksWithoutCrypto(unittest.TestCase):
    """require_crypto=False: the opt-out deployment keeps issue #117 behavior."""

    @classmethod
    def setUpClass(cls):
        cls.server_pub, cls.server_priv = create_RSA_key()

    def setUp(self):
        self.proto = _make_protocol(require_crypto=False)
        self.proto.identity = _real_key_identity(self.server_pub, self.server_priv)
        self.proto.handle_bus_message = MagicMock()
        self.client = _make_client(self.proto)

    def test_hivemessage_payload_intercom_is_delivered(self):
        frame = HiveMessage(HiveMessageType.INTERCOM, payload=_inner_bus())
        assert self.proto.handle_intercom_message(frame, self.client) is True
        self.proto.handle_bus_message.assert_called_once()

    def test_plaintext_dict_intercom_is_delivered(self):
        frame = HiveMessage(HiveMessageType.INTERCOM,
                            payload=_inner_bus().serialize())
        assert self.proto.handle_intercom_message(frame, self.client) is True
        self.proto.handle_bus_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()
