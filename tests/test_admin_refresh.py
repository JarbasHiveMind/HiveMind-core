"""``_install_client_session`` decides whether to NAT the session id based on
admin standing. That standing now gates un-NATted write access to the
orchestrator's device-local "default" session, so it must be re-checked from
the DB on each admission -- mirroring how ``MessageTypeACLPolicy`` refreshes
``allowed_types`` via ``client.resolve_user(db)`` -- instead of trusted from
the connect-time ``client.is_admin`` snapshot forever (HIVEMIND-BRIDGE-1
§4/§4.1).
"""
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)


def _make_protocol(db):
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.get_bus.return_value = agent.bus
    agent.callbacks = MagicMock()

    return HiveMindListenerProtocol(agent_protocol=agent, db=db,
                                    require_crypto=False,
                                    handshake_enabled=False)


def _make_client(protocol, sess, is_admin, key="test-key", name="test-client"):
    client = HiveMindClientConnection(
        key=key,
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=protocol,
        sess=sess,
    )
    client.name = name
    client.is_admin = is_admin
    client.allowed_types = ["recognizer_loop:utterance"]
    return client


def _stamp(protocol, client):
    return protocol._install_client_session(
        Message("recognizer_loop:utterance", {"utterances": ["hi"]}), client)


def test_revoked_admin_is_natted_at_next_message():
    db_user = MagicMock(is_admin=True)
    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    protocol = _make_protocol(db)
    client = _make_client(protocol, Session(session_id="default"), is_admin=True)

    first = _stamp(protocol, client)
    assert first.context["session"]["session_id"] == "default"

    # operator revokes admin in the DB, then forces the connection's cached
    # resolved-user to expire (mirrors resolve_user's TTL elapsing).
    db_user.is_admin = False
    client.invalidate_user()

    second = _stamp(protocol, client)
    session_id = second.context["session"]["session_id"]
    assert session_id != "default"
    assert session_id.endswith(":default")


def test_granted_admin_takes_effect_at_next_message():
    db_user = MagicMock(is_admin=False)
    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    protocol = _make_protocol(db)
    client = _make_client(protocol, Session(session_id="default"), is_admin=False)

    first = _stamp(protocol, client)
    assert first.context["session"]["session_id"] != "default"

    db_user.is_admin = True
    client.invalidate_user()

    second = _stamp(protocol, client)
    assert second.context["session"]["session_id"] == "default"


def _broadcast_hivemessage():
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("speak", {"utterance": "hi"}))
    return HiveMessage(HiveMessageType.BROADCAST, payload=inner)


def test_revoked_admin_loses_broadcast_at_next_message():
    """``handle_broadcast_message`` reads ``client.is_admin`` directly, not
    ``resolve_user``. It must still see a revoked admin's new standing at the
    connection's next message, because ``handle_message`` — the common
    dispatcher for every inbound message type — refreshes ``client.is_admin``
    from the DB before dispatching (HIVEMIND-BRIDGE-1 §4/§4.1)."""
    db_user = MagicMock(is_admin=True)
    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    protocol = _make_protocol(db)
    client = _make_client(protocol, Session(session_id="default"), is_admin=True)
    client.can_broadcast = True
    protocol.clients = {}
    protocol.illegal_callback = None
    protocol.broadcast_callback = MagicMock()
    protocol.identity = MagicMock(public_key="pubkey-master", site_id=None)

    # while still admin, broadcast is allowed
    protocol.handle_message(_broadcast_hivemessage(), client)
    protocol.broadcast_callback.assert_called_once()
    client.disconnect.assert_not_called()

    # operator revokes admin in the DB
    db_user.is_admin = False
    protocol.broadcast_callback.reset_mock()

    protocol.handle_message(_broadcast_hivemessage(), client)
    protocol.broadcast_callback.assert_not_called()
    client.disconnect.assert_called_once_with()
    assert client.is_admin is False


def test_resolve_failure_falls_back_to_connection_snapshot():
    db = MagicMock()
    db.get_client_by_api_key.return_value = None

    protocol = _make_protocol(db)
    client = _make_client(protocol, Session(session_id="default"), is_admin=True)

    message = _stamp(protocol, client)
    assert message.context["session"]["session_id"] == "default"
