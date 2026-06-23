"""Regression tests for issue #116 — illegal BROADCAST/PROPAGATE/ESCALATE
must disconnect the offending client.

When a non-admin / unprivileged client sends a BROADCAST, PROPAGATE or
ESCALATE it tried to fire ``illegal_callback`` and then ``return`` with an
unfulfilled ``# TODO kick client``. ``handle_query_message`` and
``handle_cascade_message`` already call ``client.disconnect()`` on the
equivalent permission violation; these three must mirror that so a
misbehaving peer is actually kicked.
"""
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindListenerProtocol


def _make_protocol():
    proto = object.__new__(HiveMindListenerProtocol)
    proto.peer = "master:0.0.0.0"
    proto.clients = {}
    proto.illegal_callback = MagicMock()
    proto.broadcast_callback = MagicMock()
    proto.propagate_callback = MagicMock()
    proto.escalate_callback = MagicMock()
    return proto


def _make_client(**flags):
    client = MagicMock()
    client.peer = "evil::abc"
    # default-deny the privilege relevant to each test
    client.is_admin = flags.get("is_admin", False)
    client.can_propagate = flags.get("can_propagate", False)
    client.can_escalate = flags.get("can_escalate", False)
    return client


def _wrap(outer_type):
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("speak", {"utterance": "hi"}))
    return HiveMessage(outer_type, payload=inner)


def test_illegal_broadcast_disconnects():
    proto = _make_protocol()
    client = _make_client(is_admin=False)
    proto.handle_broadcast_message(_wrap(HiveMessageType.BROADCAST), client)
    proto.illegal_callback.assert_called_once()
    client.disconnect.assert_called_once_with()
    proto.broadcast_callback.assert_not_called()


def test_illegal_propagate_disconnects():
    proto = _make_protocol()
    client = _make_client(can_propagate=False)
    proto.handle_propagate_message(_wrap(HiveMessageType.PROPAGATE), client)
    proto.illegal_callback.assert_called_once()
    client.disconnect.assert_called_once_with()
    proto.propagate_callback.assert_not_called()


def test_illegal_escalate_disconnects():
    proto = _make_protocol()
    client = _make_client(can_escalate=False)
    proto.handle_escalate_message(_wrap(HiveMessageType.ESCALATE), client)
    proto.illegal_callback.assert_called_once()
    client.disconnect.assert_called_once_with()
    proto.escalate_callback.assert_not_called()


def test_authorized_broadcast_does_not_disconnect():
    proto = _make_protocol()
    client = _make_client(is_admin=True)
    proto.handle_broadcast_message(_wrap(HiveMessageType.BROADCAST), client)
    client.disconnect.assert_not_called()
    proto.broadcast_callback.assert_called_once()
