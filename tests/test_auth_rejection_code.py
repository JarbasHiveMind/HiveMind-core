"""A refused identity must be distinguishable from a dropped network.

A bare close looks exactly like a flaky link, so a satellite retries
credentials that will never work — and because its socket did open, it reports
itself connected the whole time. The client library already raises on the
transport's authentication-failure code (WebSocket 1008); it never saw one for
a handshake rejection, because those closed bare.
"""
from unittest.mock import MagicMock

from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindClientConnection, HiveMindListenerProtocol


def _client(protocol, with_reject=True):
    client = HiveMindClientConnection(
        key="access-key",
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        reject=MagicMock() if with_reject else None,
        hm_protocol=protocol,
    )
    client.name = "sat"
    return client


def _protocol():
    return HiveMindListenerProtocol(agent_protocol=MagicMock(), db=MagicMock())


def test_a_failed_noise_handshake_says_the_identity_was_refused():
    protocol = _protocol()
    client = _client(protocol)

    protocol._abort_noise_handshake(client, "static key contradicts the pinned key")

    client.reject.assert_called_once()
    assert "pinned key" in client.reject.call_args[0][0], "the peer must be told why"
    client.disconnect.assert_not_called(), "a bare close is the bug"


def test_a_failed_password_handshake_says_the_identity_was_refused():
    protocol = _protocol()
    client = _client(protocol)
    client.pswd_handshake = MagicMock()
    client.pswd_handshake.receive_and_verify.return_value = False

    protocol.handle_handshake_message(
        HiveMessage(HiveMessageType.HANDSHAKE, {"envelope": "nope"}), client)

    client.reject.assert_called_once()
    client.disconnect.assert_not_called()


def test_a_transport_without_reject_still_closes():
    """`reject` is optional, so a transport that predates it keeps working."""
    protocol = _protocol()
    client = _client(protocol, with_reject=False)

    protocol._abort_noise_handshake(client, "bad key")

    client.disconnect.assert_called_once()


def test_a_broken_reject_callback_still_closes_the_connection():
    """Leaving a refused peer connected is worse than closing it bluntly."""
    protocol = _protocol()
    client = _client(protocol)
    client.reject.side_effect = RuntimeError("transport is gone")

    protocol._abort_noise_handshake(client, "bad key")

    client.disconnect.assert_called_once()
