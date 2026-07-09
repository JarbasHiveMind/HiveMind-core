"""BROADCAST admission honours the per-client ``can_broadcast`` ACL.

Broadcast has always required ``is_admin``. ``can_broadcast`` is a ``Client``
DB field that the websocket and mqtt transports copy onto the connection, but
the listener never read it — an admin with ``can_broadcast=False`` could still
broadcast. ``can_broadcast`` narrows an admin; it never grants rights to a
non-admin.
"""
from unittest.mock import MagicMock

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message

from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)


def _protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    proto = HiveMindListenerProtocol(agent_protocol=agent, db=MagicMock())
    proto.broadcast_callback = MagicMock()
    proto.illegal_callback = MagicMock()
    return proto


def _client(proto, **kwargs):
    client = HiveMindClientConnection(
        key="k", send_msg=MagicMock(), disconnect=MagicMock(),
        hm_protocol=proto, **kwargs)
    client.name = "caster"
    return client


def _broadcast():
    return HiveMessage(
        HiveMessageType.BROADCAST,
        payload=HiveMessage(HiveMessageType.BUS,
                            payload=Message("test.event", {"ping": "pong"})),
    )


def test_admin_with_can_broadcast_is_relayed():
    proto = _protocol()
    client = _client(proto, is_admin=True, can_broadcast=True)

    proto.handle_broadcast_message(_broadcast(), client)

    proto.broadcast_callback.assert_called_once()
    proto.illegal_callback.assert_not_called()
    client.disconnect.assert_not_called()


def test_admin_without_can_broadcast_is_refused():
    proto = _protocol()
    client = _client(proto, is_admin=True, can_broadcast=False)

    proto.handle_broadcast_message(_broadcast(), client)

    proto.broadcast_callback.assert_not_called()
    proto.illegal_callback.assert_called_once()
    client.disconnect.assert_called_once()


def test_non_admin_is_refused_even_with_can_broadcast():
    """can_broadcast narrows admin rights; it never grants them."""
    proto = _protocol()
    client = _client(proto, is_admin=False, can_broadcast=True)

    proto.handle_broadcast_message(_broadcast(), client)

    proto.broadcast_callback.assert_not_called()
    proto.illegal_callback.assert_called_once()
    client.disconnect.assert_called_once()


def test_can_broadcast_defaults_to_true():
    """Existing deployments keep the prior is_admin-only behaviour."""
    proto = _protocol()
    client = _client(proto, is_admin=True)

    assert client.can_broadcast is True
    proto.handle_broadcast_message(_broadcast(), client)
    proto.broadcast_callback.assert_called_once()
