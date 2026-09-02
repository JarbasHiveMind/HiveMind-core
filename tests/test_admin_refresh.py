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


def test_revoked_admin_is_natted_after_slow_transformer():
    """A transformer plugin can outlive resolve_user's TTL (an LLM call, a
    network round trip). If the DB revokes the admin while it runs, the
    post-transformer session-id re-stamp in handle_inject_agent_msg must see
    the fresh standing, not the dispatch-time ``client.is_admin`` snapshot
    taken before the chain ran."""
    db_user = MagicMock(is_admin=True)
    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    protocol = _make_protocol(db)
    protocol.policy_chain = MagicMock()
    protocol.policy_chain.review.return_value = MagicMock(denied=False)

    client = _make_client(protocol, Session(session_id="default"), is_admin=True)

    def revoke_mid_transform(context):
        # models the DB row changing + the cached resolve TTL elapsing while
        # this transformer was blocked on something slow.
        db_user.is_admin = False
        client.invalidate_user()
        return context

    protocol.metadata_transformers = MagicMock()
    protocol.metadata_transformers.plugins = {"fake": MagicMock()}
    protocol.metadata_transformers.transform.side_effect = revoke_mid_transform
    protocol.utterance_transformers = MagicMock()
    protocol.utterance_transformers.plugins = {}

    message = Message("recognizer_loop:utterance", {"utterances": ["hi"]},
                       {"session": {"session_id": "default"}})

    protocol.handle_inject_agent_msg(message, client)

    emitted = protocol.get_bus(client).emit.call_args[0][0]
    session_id = emitted.context["session"]["session_id"]
    assert session_id == f"{client.conn_nonce}:default"
    assert session_id != "default"
    assert client.is_admin is False


def _escalate_hivemessage():
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("speak", {"utterance": "hi"}))
    return HiveMessage(HiveMessageType.ESCALATE, payload=inner)


def _propagate_hivemessage():
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("speak", {"utterance": "hi"}))
    return HiveMessage(HiveMessageType.PROPAGATE, payload=inner)


def test_revoked_can_escalate_is_denied_at_next_message():
    """``handle_escalate_message`` reads ``client.can_escalate`` directly, not
    ``resolve_user``. A live revoke of ``can_escalate`` must still take effect
    at the connection's next message, because ``handle_message`` -- the common
    dispatcher for every inbound message type -- refreshes ``client.can_escalate``
    from the DB before dispatching (HIVEMIND-BRIDGE-1 §4/§4.1)."""
    db_user = MagicMock(is_admin=False, can_broadcast=False, can_propagate=False,
                         can_escalate=True)
    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    protocol = _make_protocol(db)
    client = _make_client(protocol, Session(session_id="default"), is_admin=False)
    client.can_escalate = True
    client.can_propagate = False
    client.can_broadcast = False
    protocol.clients = {}
    protocol.illegal_callback = None
    protocol.escalate_callback = MagicMock()

    # while still granted, escalate is allowed
    protocol.handle_message(_escalate_hivemessage(), client)
    protocol.escalate_callback.assert_called_once()
    client.disconnect.assert_not_called()

    # operator revokes can_escalate in the DB
    db_user.can_escalate = False
    protocol.escalate_callback.reset_mock()

    protocol.handle_message(_escalate_hivemessage(), client)
    protocol.escalate_callback.assert_not_called()
    client.disconnect.assert_called_once_with()
    assert client.can_escalate is False


def test_revoked_can_propagate_is_denied_at_next_message():
    """Same as above, for ``can_propagate`` / ``handle_propagate_message``."""
    db_user = MagicMock(is_admin=False, can_broadcast=False, can_propagate=True,
                         can_escalate=False)
    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    protocol = _make_protocol(db)
    client = _make_client(protocol, Session(session_id="default"), is_admin=False)
    client.can_propagate = True
    client.can_escalate = False
    client.can_broadcast = False
    protocol.clients = {}
    protocol.illegal_callback = None
    protocol.propagate_callback = MagicMock()

    # while still granted, propagate is allowed
    protocol.handle_message(_propagate_hivemessage(), client)
    protocol.propagate_callback.assert_called_once()
    client.disconnect.assert_not_called()

    # operator revokes can_propagate in the DB
    db_user.can_propagate = False
    protocol.propagate_callback.reset_mock()

    protocol.handle_message(_propagate_hivemessage(), client)
    protocol.propagate_callback.assert_not_called()
    client.disconnect.assert_called_once_with()
    assert client.can_propagate is False


def test_resolve_failure_falls_back_to_connection_snapshot():
    db = MagicMock()
    db.get_client_by_api_key.return_value = None

    protocol = _make_protocol(db)
    client = _make_client(protocol, Session(session_id="default"), is_admin=True)

    message = _stamp(protocol, client)
    assert message.context["session"]["session_id"] == "default"
