"""Unit tests for HiveMindListenerProtocol."""
import threading
import pytest
from unittest.mock import MagicMock, patch, call
from ovos_bus_client.message import Message
from hivemind_core.protocol import HiveMindListenerProtocol, HiveMindClientConnection
from hivemind_bus_client.message import HiveMessage, HiveMessageType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.bus = MagicMock()
    return agent


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
def protocol(mock_agent, mock_db):
    return HiveMindListenerProtocol(
        agent_protocol=mock_agent,
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


# ---------------------------------------------------------------------------
# Existing tests
# ---------------------------------------------------------------------------

def test_protocol_init(protocol):
    assert protocol.agent_protocol is not None
    assert protocol.db is not None


def test_handle_new_client_authorized(protocol, mock_conn):
    protocol.db.get_client_by_api_key.return_value = MagicMock()
    with patch("hivemind_core.protocol.get_server_config") as mock_cfg:
        mock_cfg.return_value = {"allowed_ciphers": ["AES-GCM"], "allowed_encodings": ["JSON-B64"]}
        protocol.handle_new_client(mock_conn)
    assert mock_conn.send.called


def test_handle_message_hello(protocol, mock_conn):
    msg = HiveMessage(HiveMessageType.HELLO)
    mock_conn.is_admin = True
    protocol.db.get_client_by_api_key.return_value = MagicMock()
    if mock_conn.peer in protocol.clients:
        del protocol.clients[mock_conn.peer]
    protocol.handle_message(msg, mock_conn)
    assert mock_conn.peer in protocol.clients


def test_handle_message_bus(protocol, mock_conn):
    mock_conn.is_admin = True
    mock_conn.authorize.return_value = True
    protocol.db.get_client_by_api_key.return_value = MagicMock(
        skill_blacklist=[], intent_blacklist=[], message_blacklist=[]
    )
    payload = {"type": "utterance", "data": {"utterance": "hello"}, "context": {}}
    msg = HiveMessage(HiveMessageType.BUS, payload=payload)
    protocol.handle_message(msg, mock_conn)
    assert protocol.agent_protocol.bus.emit.called


# ---------------------------------------------------------------------------
# QUERY handler tests
# ---------------------------------------------------------------------------

def test_handle_query_no_escalate_permission_disconnects(protocol, mock_conn):
    """Client without can_escalate is disconnected."""
    mock_conn.can_escalate = False
    inner_bus = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    msg = HiveMessage(HiveMessageType.QUERY, payload=inner_bus)
    illegal_cb = MagicMock()
    protocol.illegal_callback = illegal_cb
    protocol.db.get_client_by_api_key.return_value = MagicMock()

    protocol.handle_query_message(msg, mock_conn)

    mock_conn.disconnect.assert_called_once()
    illegal_cb.assert_called_once()


def test_handle_query_calls_agent_handle_query(protocol, mock_conn):
    """QUERY with inner BUS calls agent_protocol.handle_query."""
    inner_bus = HiveMessage(HiveMessageType.BUS, payload=Message("utterance", {}))
    msg = HiveMessage(HiveMessageType.QUERY, payload=inner_bus)
    protocol.db.get_client_by_api_key.return_value = MagicMock(
        skill_blacklist=[], intent_blacklist=[], message_blacklist=[]
    )
    mock_conn.authorize.return_value = True

    protocol.handle_query_message(msg, mock_conn)

    protocol.agent_protocol.handle_query.assert_called_once()
    args = protocol.agent_protocol.handle_query.call_args[0]
    # args[0] = bus_msg, args[1] = callback, args[2] = timeout
    assert callable(args[1])
    assert isinstance(args[2], float)


def test_handle_query_callback_sends_response(protocol, mock_conn):
    """When agent callback is invoked, client receives a QUERY(BUS) response."""
    inner_bus = HiveMessage(HiveMessageType.BUS, payload=Message("utterance", {}))
    msg = HiveMessage(HiveMessageType.QUERY, payload=inner_bus)
    protocol.db.get_client_by_api_key.return_value = MagicMock(
        skill_blacklist=[], intent_blacklist=[], message_blacklist=[]
    )
    mock_conn.authorize.return_value = True

    captured_callback = None

    def fake_handle_query(bus_msg, callback, timeout):
        nonlocal captured_callback
        captured_callback = callback

    protocol.agent_protocol.handle_query.side_effect = fake_handle_query

    protocol.handle_query_message(msg, mock_conn)
    assert captured_callback is not None

    # Simulate agent answering
    response = Message("speak", {"utterance": "hello"})
    captured_callback(response)

    mock_conn.send.assert_called_once()
    sent = mock_conn.send.call_args[0][0]
    assert sent.msg_type == HiveMessageType.QUERY
    assert sent.payload.msg_type == HiveMessageType.BUS


def test_handle_query_timeout_escalates_upstream(protocol, mock_conn):
    """When agent does not answer, QUERY is escalated upstream."""
    inner_bus = HiveMessage(HiveMessageType.BUS, payload=Message("utterance", {}))
    msg = HiveMessage(HiveMessageType.QUERY, payload=inner_bus)
    protocol.db.get_client_by_api_key.return_value = MagicMock(
        skill_blacklist=[], intent_blacklist=[], message_blacklist=[]
    )
    mock_conn.authorize.return_value = True
    protocol.query_to_master = MagicMock()

    # Capture the timeout callback directly
    captured_timeout = None
    original_timer = threading.Timer

    def fake_timer(delay, fn, *a, **kw):
        nonlocal captured_timeout
        captured_timeout = fn
        t = original_timer(delay, fn, *a, **kw)
        return t

    with patch("hivemind_core.protocol.threading.Timer", side_effect=fake_timer):
        protocol.handle_query_message(msg, mock_conn)

    assert captured_timeout is not None
    # Fire timeout manually
    captured_timeout()
    protocol.query_to_master.assert_called_once()


def test_handle_query_unauthorized_bus_drops_silently(protocol, mock_conn):
    """Unauthorized BUS payload inside QUERY is dropped, no disconnect."""
    mock_conn.authorize.return_value = False
    inner_bus = HiveMessage(HiveMessageType.BUS, payload=Message("secret", {}))
    msg = HiveMessage(HiveMessageType.QUERY, payload=inner_bus)
    protocol.db.get_client_by_api_key.return_value = MagicMock(
        skill_blacklist=[], intent_blacklist=[], message_blacklist=[]
    )

    protocol.handle_query_message(msg, mock_conn)

    mock_conn.disconnect.assert_not_called()
    protocol.agent_protocol.handle_query.assert_not_called()


# ---------------------------------------------------------------------------
# CASCADE handler tests
# ---------------------------------------------------------------------------

def test_handle_cascade_no_propagate_permission_disconnects(protocol, mock_conn):
    """Client without can_propagate is disconnected."""
    mock_conn.can_propagate = False
    inner_bus = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    msg = HiveMessage(HiveMessageType.CASCADE, payload=inner_bus)
    illegal_cb = MagicMock()
    protocol.illegal_callback = illegal_cb
    protocol.db.get_client_by_api_key.return_value = MagicMock()

    protocol.handle_cascade_message(msg, mock_conn)

    mock_conn.disconnect.assert_called_once()
    illegal_cb.assert_called_once()


def test_handle_cascade_injects_bus_locally(protocol, mock_conn):
    """CASCADE with inner BUS injects into local agent bus."""
    mock_conn.is_admin = True
    mock_conn.authorize.return_value = True
    protocol.db.get_client_by_api_key.return_value = MagicMock(
        skill_blacklist=[], intent_blacklist=[], message_blacklist=[]
    )
    inner_bus = HiveMessage(HiveMessageType.BUS,
                            payload={"type": "utterance", "data": {}, "context": {}})
    msg = HiveMessage(HiveMessageType.CASCADE, payload=inner_bus)

    protocol.handle_cascade_message(msg, mock_conn)

    protocol.agent_protocol.bus.emit.assert_called()


def test_handle_cascade_floods_to_other_clients(protocol, mock_conn):
    """CASCADE is forwarded to all other connected clients."""
    mock_conn.is_admin = True
    mock_conn.authorize.return_value = True
    protocol.db.get_client_by_api_key.return_value = MagicMock(
        skill_blacklist=[], intent_blacklist=[], message_blacklist=[]
    )
    inner_bus = HiveMessage(HiveMessageType.BUS,
                            payload={"type": "utterance", "data": {}, "context": {}})
    msg = HiveMessage(HiveMessageType.CASCADE, payload=inner_bus)

    # Add two other peers
    peer_a = MagicMock()
    peer_a.peer = "peer-a::s1"
    peer_b = MagicMock()
    peer_b.peer = "peer-b::s2"
    protocol.clients["peer-a::s1"] = peer_a
    protocol.clients["peer-b::s2"] = peer_b
    # originator is mock_conn — not in clients, so flood goes to both peers
    protocol.handle_cascade_message(msg, mock_conn)

    peer_a.send.assert_called_once()
    peer_b.send.assert_called_once()


def test_handle_cascade_does_not_echo_to_sender(protocol, mock_conn):
    """CASCADE is NOT sent back to the originating client."""
    mock_conn.is_admin = True
    mock_conn.authorize.return_value = True
    protocol.db.get_client_by_api_key.return_value = MagicMock(
        skill_blacklist=[], intent_blacklist=[], message_blacklist=[]
    )
    inner_bus = HiveMessage(HiveMessageType.BUS,
                            payload={"type": "utterance", "data": {}, "context": {}})
    msg = HiveMessage(HiveMessageType.CASCADE, payload=inner_bus)

    # Register sender in clients
    protocol.clients[mock_conn.peer] = mock_conn
    protocol.handle_cascade_message(msg, mock_conn)

    # sender should not receive its own CASCADE back
    # (bus.emit is called for local injection, but conn.send should not)
    for c in mock_conn.send.call_args_list:
        sent = c[0][0]
        assert sent.msg_type != HiveMessageType.CASCADE, \
            "Sender should not receive CASCADE echo"


def test_handle_cascade_escalates_upstream(protocol, mock_conn):
    """CASCADE is forwarded upstream if relay."""
    mock_conn.is_admin = True
    mock_conn.authorize.return_value = True
    protocol.db.get_client_by_api_key.return_value = MagicMock(
        skill_blacklist=[], intent_blacklist=[], message_blacklist=[]
    )
    protocol.cascade_to_master = MagicMock()
    inner_bus = HiveMessage(HiveMessageType.BUS,
                            payload={"type": "utterance", "data": {}, "context": {}})
    msg = HiveMessage(HiveMessageType.CASCADE, payload=inner_bus)

    protocol.handle_cascade_message(msg, mock_conn)

    protocol.cascade_to_master.assert_called_once()


# ---------------------------------------------------------------------------
# INTERCOM handler tests
# ---------------------------------------------------------------------------

def test_handle_intercom_not_for_us_returns_false(protocol, mock_conn):
    """INTERCOM targeted at a different public key returns False."""
    protocol.identity = MagicMock()
    protocol.identity.public_key = "our-key"
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("speak", {}))
    msg = HiveMessage(HiveMessageType.INTERCOM, payload=inner)
    msg._metadata = {"target_public_key": "someone-elses-key"}

    result = protocol.handle_intercom_message(msg, mock_conn)
    assert result is False


def test_handle_intercom_unencrypted_trusted_dispatches(protocol, mock_conn):
    """Unencrypted INTERCOM from a trusted peer dispatches inner BUS."""
    protocol.identity = MagicMock()
    protocol.identity.public_key = "our-key"
    protocol.identity.is_trusted_key = MagicMock(return_value=True)
    mock_conn.is_admin = True
    mock_conn.authorize.return_value = True
    protocol.db.get_client_by_api_key.return_value = MagicMock(
        skill_blacklist=[], intent_blacklist=[], message_blacklist=[]
    )

    # Register sender's public_key in hive_mapper so trust check works
    from hivemind_bus_client.hive_map import NodeInfo
    protocol.hive_mapper.nodes[mock_conn.peer] = NodeInfo(
        peer=mock_conn.peer, public_key="trusted-peer-key"
    )

    inner_payload = {"type": "utterance", "data": {"utterances": ["hi"]}, "context": {}}
    inner = HiveMessage(HiveMessageType.BUS, payload=inner_payload)
    msg = HiveMessage(HiveMessageType.INTERCOM, payload=inner)
    # No target_public_key — broadcast INTERCOM

    result = protocol.handle_intercom_message(msg, mock_conn)
    assert result is True
    protocol.agent_protocol.bus.emit.assert_called()


def test_handle_intercom_untrusted_drops(protocol, mock_conn):
    """Unencrypted INTERCOM from an untrusted peer is dropped."""
    protocol.identity = MagicMock()
    protocol.identity.public_key = "our-key"
    protocol.identity.is_trusted_key = MagicMock(return_value=False)

    inner = HiveMessage(HiveMessageType.BUS, payload=Message("speak", {}))
    msg = HiveMessage(HiveMessageType.INTERCOM, payload=inner)

    result = protocol.handle_intercom_message(msg, mock_conn)
    assert result is False
    protocol.agent_protocol.bus.emit.assert_not_called()


# ---------------------------------------------------------------------------
# Relay method tests
# ---------------------------------------------------------------------------

def test_query_to_master_no_upstream_is_noop(protocol):
    """query_to_master is a no-op when no upstream is bound."""
    assert protocol._upstream_hm is None
    payload = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    # Should not raise
    protocol.query_to_master(payload)


def test_cascade_to_master_no_upstream_is_noop(protocol):
    """cascade_to_master is a no-op when no upstream is bound."""
    assert protocol._upstream_hm is None
    payload = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    protocol.cascade_to_master(payload)


def test_query_to_master_emits_upstream(protocol):
    """query_to_master emits a QUERY HiveMessage to upstream."""
    upstream = MagicMock()
    protocol._upstream_hm = upstream
    payload = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    protocol.query_to_master(payload)
    upstream.emit.assert_called_once()
    sent = upstream.emit.call_args[0][0]
    assert sent.msg_type == HiveMessageType.QUERY


def test_cascade_to_master_emits_upstream(protocol):
    """cascade_to_master emits a CASCADE HiveMessage to upstream."""
    upstream = MagicMock()
    protocol._upstream_hm = upstream
    payload = HiveMessage(HiveMessageType.BUS, payload=Message("test", {}))
    protocol.cascade_to_master(payload)
    upstream.emit.assert_called_once()
    sent = upstream.emit.call_args[0][0]
    assert sent.msg_type == HiveMessageType.CASCADE
