"""BROADCAST must honour the ``can_broadcast`` grant on the client row.

``Client.can_broadcast`` is a column in the hivemind-plugin-manager database
and the websocket protocol plugin copies it onto the live connection, but
``HiveMindClientConnection`` never declared the field and
``handle_broadcast_message`` gated on ``is_admin`` alone. An operator who
revoked broadcast on a client saw no change in behaviour.

The gate is now ``is_admin and can_broadcast``: admin is still required (the
DB default is ``can_broadcast=True``, so gating on it alone would hand
broadcast to every client), and revoking the grant now actually works.
"""
import dataclasses
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindClientConnection, HiveMindListenerProtocol


def _make_protocol():
    proto = object.__new__(HiveMindListenerProtocol)
    proto.peer = "master:0.0.0.0"
    # provenance is stamped from the node public key, so a hand-built
    # protocol needs an identity even when the test is about permissions
    proto.identity = MagicMock(public_key="pubkey-master", site_id=None)
    proto.clients = {}
    proto.illegal_callback = MagicMock()
    proto.broadcast_callback = MagicMock()
    return proto


def _make_client(is_admin: bool, can_broadcast: bool) -> MagicMock:
    client = MagicMock()
    client.peer = "node::abc"
    client.is_admin = is_admin
    client.can_broadcast = can_broadcast
    return client


def _broadcast() -> HiveMessage:
    inner = HiveMessage(HiveMessageType.BUS,
                        payload=Message("speak", {"utterance": "hi"}))
    return HiveMessage(HiveMessageType.BROADCAST, payload=inner)


def test_connection_declares_can_broadcast():
    """The grant must be a real field, like ``can_escalate``/``can_propagate``,
    not a stray attribute assigned by the transport plugin."""
    fields = {f.name: f for f in dataclasses.fields(HiveMindClientConnection)}
    assert "can_broadcast" in fields, \
        "HiveMindClientConnection must declare can_broadcast"
    assert fields["can_broadcast"].default is True, \
        "default must match the Client DB column default (True)"


def test_revoked_broadcast_is_denied_even_for_admin():
    proto = _make_protocol()
    client = _make_client(is_admin=True, can_broadcast=False)
    proto.handle_broadcast_message(_broadcast(), client)
    proto.broadcast_callback.assert_not_called()
    proto.illegal_callback.assert_called_once()
    client.disconnect.assert_called_once_with()


def test_granted_broadcast_is_allowed_for_admin():
    proto = _make_protocol()
    client = _make_client(is_admin=True, can_broadcast=True)
    proto.handle_broadcast_message(_broadcast(), client)
    proto.broadcast_callback.assert_called_once()
    client.disconnect.assert_not_called()


def test_grant_alone_does_not_promote_a_non_admin():
    """``can_broadcast`` defaults to True on every DB row, so it may only
    narrow the admin privilege, never widen it to ordinary clients."""
    proto = _make_protocol()
    client = _make_client(is_admin=False, can_broadcast=True)
    proto.handle_broadcast_message(_broadcast(), client)
    proto.broadcast_callback.assert_not_called()
    client.disconnect.assert_called_once_with()
