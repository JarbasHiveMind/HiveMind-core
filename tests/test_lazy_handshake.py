"""The RSA handshake is built on first use, not on connection construction.

Transports build a HiveMindClientConnection before they can validate the
api_key, so an eager handshake made every rejected connection parse the node's
private key first.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hivemind_core.protocol import HiveMindClientConnection


def _connection(**kwargs):
    return HiveMindClientConnection(
        key="k", send_msg=MagicMock(), disconnect=MagicMock(),
        hm_protocol=SimpleNamespace(
            identity=SimpleNamespace(private_key="/nonexistent/key.pem")),
        **kwargs,
    )


def test_construction_does_not_build_a_handshake():
    with patch("hivemind_core.protocol.HandShake") as handshake:
        client = _connection()
        handshake.assert_not_called()
    assert client._handshake is None


def test_handshake_is_built_on_first_access_and_cached():
    with patch("hivemind_core.protocol.HandShake") as handshake:
        client = _connection()
        first = client.handshake
        second = client.handshake

    handshake.assert_called_once_with("/nonexistent/key.pem")
    assert first is second


def test_handshake_can_be_injected():
    injected = MagicMock()
    with patch("hivemind_core.protocol.HandShake") as handshake:
        client = _connection()
        client.handshake = injected
        assert client.handshake is injected
        handshake.assert_not_called()


def test_rejected_connection_never_parses_the_identity_key():
    """A connection built for an invalid api_key is discarded untouched."""
    with patch("hivemind_core.protocol.HandShake") as handshake:
        client = _connection()
        # what a transport does on a key miss: hand the client to the
        # invalid-key callback, then drop it
        client.disconnect()
        handshake.assert_not_called()
    assert client._handshake is None
