"""Regression test — an exception raised inside any ``handle_message``
dispatch arm must not propagate into the transport.

Every transport (websocket, http, mqtt, usenet, email) calls
``HiveMindListenerProtocol.handle_message`` with no ``try``/``except`` of its
own. On websocket, an uncaught exception is caught by Tornado's
``_run_callback``, which calls ``_abort()`` and tears down the raw socket
with no close frame — indistinguishable from a network drop, so a satellite
reconnects forever into the same fault. ``handle_message`` must catch any
handler exception itself, log it, and close the connection with an explicit
code and reason, mirroring the invalid-key path elsewhere in the same file.
"""
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindListenerProtocol


def _make_protocol():
    proto = object.__new__(HiveMindListenerProtocol)
    proto.peer = "master:0.0.0.0"
    proto.identity = MagicMock(public_key="master-pubkey")
    proto.clients = {}
    proto.db = None
    return proto


def _make_client():
    client = MagicMock()
    client.peer = "satellite::abc"
    client.is_admin = False
    return client


def test_handler_exception_does_not_propagate_and_disconnects():
    proto = _make_protocol()
    client = _make_client()
    message = HiveMessage(HiveMessageType.BUS, payload=Message("speak", {"utterance": "hi"}))

    with patch.object(proto, "handle_bus_message", side_effect=RuntimeError("boom")), \
         patch("hivemind_core.protocol.LOG") as mock_log:
        # must not raise
        proto.handle_message(message, client)

    client.disconnect.assert_called_once()
    args, _ = client.disconnect.call_args
    assert args[0] == 1011
    assert args[1] == "internal error handling bus"
    mock_log.exception.assert_called_once()
    logged_text = mock_log.exception.call_args[0][0]
    assert "bus handler" in logged_text


def test_handler_exception_on_wire_message_still_disconnects():
    """On the wire, ``HiveMessage.deserialize`` yields a plain ``str``
    ``msg_type`` (no ``.value``, unlike the ``HiveMessageType`` enum used
    above), so the except block must format it without assuming an enum."""
    proto = _make_protocol()
    client = _make_client()
    wire = HiveMessage(HiveMessageType.BUS, payload=Message("speak", {"utterance": "hi"})).serialize()
    message = HiveMessage.deserialize(wire)
    assert isinstance(message.msg_type, str)

    with patch.object(proto, "handle_bus_message", side_effect=RuntimeError("boom")), \
         patch("hivemind_core.protocol.LOG") as mock_log:
        # must not raise, even though msg_type has no .value here
        proto.handle_message(message, client)

    client.disconnect.assert_called_once_with(1011, "internal error handling bus")
    mock_log.exception.assert_called_once()
    logged_text = mock_log.exception.call_args[0][0]
    assert "bus handler" in logged_text
