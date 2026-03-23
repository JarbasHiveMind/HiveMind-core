"""Additional protocol tests to improve coverage of uncovered handlers."""
import pytest
from unittest.mock import MagicMock, patch, call
from ovos_bus_client.message import Message
from hivemind_core.protocol import HiveMindListenerProtocol, HiveMindClientConnection
from hivemind_bus_client.message import HiveMessage, HiveMessageType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db():
    db = MagicMock()
    db.__enter__.return_value = db
    db.__exit__ = MagicMock(return_value=False)
    db.get_client_by_api_key.return_value = MagicMock(
        skill_blacklist=[], intent_blacklist=[], message_blacklist=[]
    )
    return db


@pytest.fixture
def protocol(mock_db):
    agent = MagicMock()
    agent.bus = MagicMock()
    return HiveMindListenerProtocol(
        agent_protocol=agent,
        binary_data_protocol=MagicMock(),
        db=mock_db,
    )


@pytest.fixture
def mock_conn():
    conn = MagicMock()
    conn.key = "test-key"
    conn.peer = "test-peer::sess1"
    conn.sess = MagicMock()
    conn.sess.session_id = "sess1"
    conn.sess.site_id = "test-site"
    conn.sess.serialize.return_value = {}
    conn.is_admin = True
    conn.can_escalate = True
    conn.can_propagate = True
    conn.send = MagicMock()
    conn.disconnect = MagicMock()
    conn.authorize.return_value = True
    return conn


def _make_peer(peer_id: str) -> MagicMock:
    c = MagicMock()
    c.peer = peer_id
    c.send = MagicMock()
    return c


# ---------------------------------------------------------------------------
# HiveMindClientConnection.authorize
# ---------------------------------------------------------------------------

def test_authorize_empty_allowed_types_permits_all():
    conn = MagicMock(spec=HiveMindClientConnection)
    conn.allowed_types = []
    result = HiveMindClientConnection.authorize(conn, Message("anything", {}))
    assert result is True


def test_authorize_whitelist_blocks_unlisted():
    conn = MagicMock(spec=HiveMindClientConnection)
    conn.allowed_types = ["recognizer_loop:utterance"]
    result = HiveMindClientConnection.authorize(conn, Message("speak", {}))
    assert result is False


def test_authorize_whitelist_permits_listed():
    conn = MagicMock(spec=HiveMindClientConnection)
    conn.allowed_types = ["recognizer_loop:utterance"]
    result = HiveMindClientConnection.authorize(conn, Message("recognizer_loop:utterance", {}))
    assert result is True


# ---------------------------------------------------------------------------
# handle_hello_message
# ---------------------------------------------------------------------------

def test_hello_registers_client(protocol, mock_conn):
    if mock_conn.peer in protocol.clients:
        del protocol.clients[mock_conn.peer]
    msg = HiveMessage(HiveMessageType.HELLO, payload={"session": {"session_id": "sess1"}})
    with patch("hivemind_core.protocol.Session") as mock_sess:
        mock_sess.deserialize.return_value = mock_conn.sess
        protocol.handle_hello_message(msg, mock_conn)
    assert mock_conn.peer in protocol.clients


def test_hello_default_session_non_admin_disconnects(protocol, mock_conn):
    mock_conn.is_admin = False
    mock_conn.sess.session_id = "default"
    msg = HiveMessage(HiveMessageType.HELLO, payload={})
    with patch("hivemind_core.protocol.Session") as mock_sess:
        s = MagicMock()
        s.session_id = "default"
        mock_sess.deserialize.return_value = s
        protocol.handle_hello_message(msg, mock_conn)
    mock_conn.disconnect.assert_called_once()


def test_hello_updates_site_id(protocol, mock_conn):
    msg = HiveMessage(HiveMessageType.HELLO, payload={"site_id": "kitchen"})
    protocol.handle_hello_message(msg, mock_conn)
    assert mock_conn.sess.site_id == "kitchen"


# ---------------------------------------------------------------------------
# handle_bus_message
# ---------------------------------------------------------------------------

def test_bus_message_injects_into_agent_bus(protocol, mock_conn):
    mock_conn.is_admin = True
    mock_conn.authorize.return_value = True
    payload = {"type": "recognizer_loop:utterance", "data": {"utterances": ["hi"]}, "context": {}}
    msg = HiveMessage(HiveMessageType.BUS, payload=payload)
    protocol.handle_bus_message(msg, mock_conn)
    protocol.agent_protocol.bus.emit.assert_called()


def test_bus_message_default_session_non_admin_disconnects(protocol, mock_conn):
    mock_conn.is_admin = False
    msg = HiveMessage(HiveMessageType.BUS,
                      payload={"type": "speak", "data": {}, "context": {"session": {"session_id": "default"}}})
    protocol.handle_bus_message(msg, mock_conn)
    mock_conn.disconnect.assert_called_once()


def test_bus_message_calls_agent_bus_callback(protocol, mock_conn):
    cb = MagicMock()
    protocol.agent_bus_callback = cb
    mock_conn.authorize.return_value = True
    payload = {"type": "utterance", "data": {}, "context": {}}
    msg = HiveMessage(HiveMessageType.BUS, payload=payload)
    protocol.handle_bus_message(msg, mock_conn)
    cb.assert_called()


# ---------------------------------------------------------------------------
# handle_broadcast_message
# ---------------------------------------------------------------------------

def test_broadcast_non_admin_disconnects(protocol, mock_conn):
    mock_conn.is_admin = False
    illegal_cb = MagicMock()
    protocol.illegal_callback = illegal_cb
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    msg = HiveMessage(HiveMessageType.BROADCAST, payload=inner)
    protocol.handle_broadcast_message(msg, mock_conn)
    mock_conn.disconnect.assert_called_once()
    illegal_cb.assert_called_once()


def test_broadcast_floods_to_other_clients(protocol, mock_conn):
    mock_conn.is_admin = True
    peer_a = _make_peer("peer-a::s1")
    peer_b = _make_peer("peer-b::s2")
    protocol.clients["peer-a::s1"] = peer_a
    protocol.clients["peer-b::s2"] = peer_b
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    msg = HiveMessage(HiveMessageType.BROADCAST, payload=inner)
    protocol.handle_broadcast_message(msg, mock_conn)
    peer_a.send.assert_called_once()
    peer_b.send.assert_called_once()


def test_broadcast_no_echo_to_sender(protocol, mock_conn):
    mock_conn.is_admin = True
    protocol.clients[mock_conn.peer] = mock_conn
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    msg = HiveMessage(HiveMessageType.BROADCAST, payload=inner)
    # reset send mock so we only track broadcast echo
    mock_conn.send.reset_mock()
    protocol.handle_broadcast_message(msg, mock_conn)
    for c in mock_conn.send.call_args_list:
        assert c[0][0].msg_type != HiveMessageType.BROADCAST, "Sender should not receive BROADCAST echo"


def test_broadcast_calls_broadcast_callback(protocol, mock_conn):
    mock_conn.is_admin = True
    cb = MagicMock()
    protocol.broadcast_callback = cb
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    msg = HiveMessage(HiveMessageType.BROADCAST, payload=inner)
    protocol.handle_broadcast_message(msg, mock_conn)
    cb.assert_called_once()


# ---------------------------------------------------------------------------
# handle_propagate_message
# ---------------------------------------------------------------------------

def test_propagate_no_permission_disconnects(protocol, mock_conn):
    mock_conn.can_propagate = False
    illegal_cb = MagicMock()
    protocol.illegal_callback = illegal_cb
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    msg = HiveMessage(HiveMessageType.PROPAGATE, payload=inner)
    protocol.handle_propagate_message(msg, mock_conn)
    mock_conn.disconnect.assert_called_once()
    illegal_cb.assert_called_once()


def test_propagate_forwards_to_other_clients(protocol, mock_conn):
    peer_a = _make_peer("peer-a::s1")
    protocol.clients["peer-a::s1"] = peer_a
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    msg = HiveMessage(HiveMessageType.PROPAGATE, payload=inner)
    protocol.handle_propagate_message(msg, mock_conn)
    peer_a.send.assert_called_once()
    sent = peer_a.send.call_args[0][0]
    assert sent.msg_type == HiveMessageType.PROPAGATE


def test_propagate_no_echo_to_sender(protocol, mock_conn):
    protocol.clients[mock_conn.peer] = mock_conn
    mock_conn.send.reset_mock()
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    msg = HiveMessage(HiveMessageType.PROPAGATE, payload=inner)
    protocol.handle_propagate_message(msg, mock_conn)
    for c in mock_conn.send.call_args_list:
        assert c[0][0].msg_type != HiveMessageType.PROPAGATE


def test_propagate_calls_propagate_callback(protocol, mock_conn):
    cb = MagicMock()
    protocol.propagate_callback = cb
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    msg = HiveMessage(HiveMessageType.PROPAGATE, payload=inner)
    protocol.handle_propagate_message(msg, mock_conn)
    cb.assert_called_once()


def test_propagate_escalates_upstream(protocol, mock_conn):
    protocol.propagate_to_master = MagicMock()
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    msg = HiveMessage(HiveMessageType.PROPAGATE, payload=inner)
    protocol.handle_propagate_message(msg, mock_conn)
    protocol.propagate_to_master.assert_called_once()


# ---------------------------------------------------------------------------
# handle_escalate_message
# ---------------------------------------------------------------------------

def test_escalate_no_permission_disconnects(protocol, mock_conn):
    mock_conn.can_escalate = False
    illegal_cb = MagicMock()
    protocol.illegal_callback = illegal_cb
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    msg = HiveMessage(HiveMessageType.ESCALATE, payload=inner)
    protocol.handle_escalate_message(msg, mock_conn)
    mock_conn.disconnect.assert_called_once()
    illegal_cb.assert_called_once()


def test_escalate_calls_escalate_callback(protocol, mock_conn):
    cb = MagicMock()
    protocol.escalate_callback = cb
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    msg = HiveMessage(HiveMessageType.ESCALATE, payload=inner)
    protocol.handle_escalate_message(msg, mock_conn)
    cb.assert_called_once()


def test_escalate_forwards_upstream(protocol, mock_conn):
    protocol.escalate_to_master = MagicMock()
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    msg = HiveMessage(HiveMessageType.ESCALATE, payload=inner)
    protocol.handle_escalate_message(msg, mock_conn)
    protocol.escalate_to_master.assert_called_once()


# ---------------------------------------------------------------------------
# Relay fan-out methods: *_from_master
# ---------------------------------------------------------------------------

def test_broadcast_from_master_fans_out(protocol):
    peer_a = _make_peer("a::1")
    peer_b = _make_peer("b::2")
    protocol.clients = {"a::1": peer_a, "b::2": peer_b}
    msg = HiveMessage(HiveMessageType.BROADCAST, payload=HiveMessage(HiveMessageType.BUS, payload=Message("test", {})))
    protocol.broadcast_from_master(msg)
    peer_a.send.assert_called_once_with(msg)
    peer_b.send.assert_called_once_with(msg)


def test_propagate_from_master_fans_out(protocol):
    peer_a = _make_peer("a::1")
    protocol.clients = {"a::1": peer_a}
    msg = HiveMessage(HiveMessageType.PROPAGATE, payload=HiveMessage(HiveMessageType.BUS, payload=Message("test", {})))
    protocol.propagate_from_master(msg)
    peer_a.send.assert_called_once_with(msg)


def test_query_from_master_fans_out(protocol):
    peer_a = _make_peer("a::1")
    peer_b = _make_peer("b::2")
    protocol.clients = {"a::1": peer_a, "b::2": peer_b}
    msg = HiveMessage(HiveMessageType.QUERY, payload=HiveMessage(HiveMessageType.BUS, payload=Message("test", {})))
    protocol.query_from_master(msg)
    peer_a.send.assert_called_once_with(msg)
    peer_b.send.assert_called_once_with(msg)


def test_cascade_from_master_fans_out(protocol):
    peer_a = _make_peer("a::1")
    protocol.clients = {"a::1": peer_a}
    msg = HiveMessage(HiveMessageType.CASCADE, payload=HiveMessage(HiveMessageType.BUS, payload=Message("test", {})))
    protocol.cascade_from_master(msg)
    peer_a.send.assert_called_once_with(msg)


# ---------------------------------------------------------------------------
# escalate_to_master / propagate_to_master
# ---------------------------------------------------------------------------

def test_escalate_to_master_no_upstream_is_noop(protocol):
    assert protocol._upstream_hm is None
    payload = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    protocol.escalate_to_master(payload)  # must not raise


def test_escalate_to_master_emits_upstream(protocol):
    upstream = MagicMock()
    protocol._upstream_hm = upstream
    payload = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    protocol.escalate_to_master(payload)
    upstream.emit.assert_called_once()
    sent = upstream.emit.call_args[0][0]
    assert sent.msg_type == HiveMessageType.ESCALATE


def test_propagate_to_master_no_upstream_is_noop(protocol):
    assert protocol._upstream_hm is None
    payload = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    protocol.propagate_to_master(payload)  # must not raise


def test_propagate_to_master_emits_upstream(protocol):
    upstream = MagicMock()
    protocol._upstream_hm = upstream
    payload = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    protocol.propagate_to_master(payload)
    upstream.emit.assert_called_once()
    sent = upstream.emit.call_args[0][0]
    assert sent.msg_type == HiveMessageType.PROPAGATE


# ---------------------------------------------------------------------------
# handle_client_shared_bus
# ---------------------------------------------------------------------------

def test_shared_bus_calls_callback(protocol, mock_conn):
    cb = MagicMock()
    protocol.shared_bus_callback = cb
    msg = Message("test", {})
    protocol.handle_client_shared_bus(msg, mock_conn)
    cb.assert_called_once_with(msg)


def test_shared_bus_no_callback_does_not_raise(protocol, mock_conn):
    protocol.shared_bus_callback = None
    protocol.handle_client_shared_bus(Message("test", {}), mock_conn)
