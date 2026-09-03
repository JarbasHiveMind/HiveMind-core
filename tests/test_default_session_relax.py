"""A remote peer may declare "default" at HELLO time (HIVEMIND-BRIDGE-1
§4.1). ``_install_client_session`` translates every inbound BUS message to a
per-connection Layer-1 id (``f"{conn_nonce}:{session_id}"``) before the
policy chain runs (HIVEMIND-BRIDGE-1 §4), so a non-admin's declared
"default" can not collide with, or masquerade as, the orchestrator's own
"default" session. An admin connection is trusted to skip that translation
and address the orchestrator's sessions (including the reserved,
device-local "default") directly.
"""
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.get_bus.return_value = agent.bus
    agent.callbacks = MagicMock()

    db = MagicMock()
    # No DB-backed user by default: _install_client_session falls back to
    # the connection's is_admin snapshot, which is what these tests pin.
    # See tests/test_admin_refresh.py for the DB-refresh behavior itself.
    db.get_client_by_api_key.return_value = None

    return HiveMindListenerProtocol(agent_protocol=agent, db=db)


def _make_client(protocol, sess, is_admin=False, key="test-key", name="test-client"):
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


def _hello(protocol, client):
    payload = {"session": client.sess.serialize()}
    protocol.handle_hello_message(
        HiveMessage(HiveMessageType.HELLO, payload), client)


def test_non_admin_default_hello_is_not_disconnected():
    protocol = _make_protocol()
    client = _make_client(protocol, Session(session_id="default"), is_admin=False)

    _hello(protocol, client)

    client.disconnect.assert_not_called()
    assert protocol.clients.get(client.peer) is client


def test_non_admin_default_is_natted_on_inbound():
    protocol = _make_protocol()
    client = _make_client(protocol, Session(session_id="default"), is_admin=False)
    _hello(protocol, client)

    message = protocol._install_client_session(
        Message("recognizer_loop:utterance", {"utterances": ["hi"]}), client)

    session_id = message.context["session"]["session_id"]
    assert session_id != "default"
    assert session_id.endswith(":default")


def test_two_non_admin_default_clients_isolated():
    protocol = _make_protocol()
    first = _make_client(protocol, Session(session_id="default"),
                          is_admin=False, key="key-1", name="sat-1")
    second = _make_client(protocol, Session(session_id="default"),
                           is_admin=False, key="key-2", name="sat-2")
    _hello(protocol, first)
    _hello(protocol, second)

    msg1 = protocol._install_client_session(
        Message("recognizer_loop:utterance", {"utterances": ["hi"]}), first)
    msg2 = protocol._install_client_session(
        Message("recognizer_loop:utterance", {"utterances": ["hi"]}), second)

    sid1 = msg1.context["session"]["session_id"]
    sid2 = msg2.context["session"]["session_id"]
    assert sid1 != sid2
    assert sid1.endswith(":default")
    assert sid2.endswith(":default")


def test_admin_default_still_allowed():
    protocol = _make_protocol()
    client = _make_client(protocol, Session(session_id="default"), is_admin=True)

    _hello(protocol, client)

    client.disconnect.assert_not_called()
    assert protocol.clients.get(client.peer) is client


def test_admin_skips_nat_and_reaches_default():
    protocol = _make_protocol()
    client = _make_client(protocol, Session(session_id="default"), is_admin=True)
    _hello(protocol, client)

    message = protocol._install_client_session(
        Message("recognizer_loop:utterance", {"utterances": ["hi"]}), client)

    assert message.context["session"]["session_id"] == "default"


def test_admin_arbitrary_session_not_natted():
    protocol = _make_protocol()
    client = _make_client(protocol, Session(session_id="room-5"), is_admin=True)
    _hello(protocol, client)

    message = protocol._install_client_session(
        Message("recognizer_loop:utterance", {"utterances": ["hi"]}), client)

    assert message.context["session"]["session_id"] == "room-5"


def test_non_admin_default_disconnect_carries_natted_session_id():
    # the disconnect notification must carry the same Layer-1 session the
    # bus saw for this connection, not omit it and not report bare
    # "default" (BRIDGE-1 §4/§4.1).
    protocol = _make_protocol()
    client = _make_client(protocol, Session(session_id="default"), is_admin=False)
    _hello(protocol, client)

    protocol.handle_client_disconnected(client)

    emitted = protocol.agent_protocol.bus.emit.call_args[0][0]
    assert emitted.msg_type == "hive.client.disconnect"
    session_id = emitted.context["session"]["session_id"]
    assert session_id != "default"
    assert session_id.endswith(":default")


def test_admin_default_disconnect_carries_raw_session_id():
    protocol = _make_protocol()
    client = _make_client(protocol, Session(session_id="default"), is_admin=True)
    _hello(protocol, client)

    protocol.handle_client_disconnected(client)

    emitted = protocol.agent_protocol.bus.emit.call_args[0][0]
    assert emitted.msg_type == "hive.client.disconnect"
    assert emitted.context["session"]["session_id"] == "default"
