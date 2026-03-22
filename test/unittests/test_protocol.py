import pytest
from unittest.mock import MagicMock, patch
from hivemind_core.protocol import HiveMindListenerProtocol, HiveMindClientConnection
from hivemind_bus_client.message import HiveMessage, HiveMessageType

@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.bus = MagicMock()
    return agent

@pytest.fixture
def mock_bin():
    return MagicMock()

@pytest.fixture
def mock_db():
    db = MagicMock()
    # Handle 'with self.db:'
    db.__enter__.return_value = db
    # If update_last_seen calls self.db.get_client_by_api_key, we need this:
    db.get_client_by_api_key.return_value = MagicMock()
    return db

@pytest.fixture
def protocol(mock_agent, mock_bin, mock_db):
    return HiveMindListenerProtocol(
        agent_protocol=mock_agent,
        binary_data_protocol=mock_bin,
        db=mock_db
    )

@pytest.fixture
def mock_conn():
    conn = MagicMock()
    conn.key = "test-key"
    conn.peer = "test-peer"
    conn.sess = MagicMock()
    conn.sess.session_id = "test-session-id"
    conn.sess.site_id = "test-site"
    conn.is_admin = False
    conn.send_msg = MagicMock()
    conn.send = MagicMock() # Protocol calls .send() which calls .send_msg()
    conn.disconnect = MagicMock()
    conn.authorize.return_value = True
    # mock decode to return the message itself if it's already one, or wrap it
    conn.decode.side_effect = lambda p: p if hasattr(p, "msg_type") else HiveMessage(HiveMessageType.HELLO)
    return conn

def test_protocol_init(protocol):
    assert protocol.agent_protocol is not None
    assert protocol.db is not None

def test_handle_new_client_authorized(protocol, mock_conn):
    # Setup DB to return a user
    mock_user = MagicMock()
    mock_user.api_key = "test-key"
    protocol.db.get_client_by_api_key.return_value = mock_user
    
    with patch("hivemind_core.protocol.get_server_config") as mock_cfg:
        mock_cfg.return_value = {"allowed_ciphers": ["AES-GCM"], "allowed_encodings": ["JSON-B64"]}
        protocol.handle_new_client(mock_conn)
    
    # handle_new_client does NOT call get_client_by_api_key directly
    # it emits a message to the bus. 
    # But it calls update_last_seen if it was authorized? 
    # Actually looking at L260-315 it doesn't seem to call DB.
    # Let's verify what it DOES call.
    assert mock_conn.send.called

def test_handle_message_hello(protocol, mock_conn):
    msg = HiveMessage(HiveMessageType.HELLO)
    mock_conn.is_admin = True
    
    # Setup DB for authorization check inside handle_message -> update_last_seen
    mock_user = MagicMock()
    mock_user.api_key = "test-key"
    protocol.db.get_client_by_api_key.return_value = mock_user
    
    # Ensure client is NOT in clients initially
    if mock_conn.peer in protocol.clients:
        del protocol.clients[mock_conn.peer]
    
    protocol.handle_message(msg, mock_conn)
    
    # handle_hello_message adds client to protocol.clients
    assert mock_conn.peer in protocol.clients
    assert protocol.clients[mock_conn.peer] == mock_conn

def test_handle_message_bus(protocol, mock_conn):
    # BUS message requires authorized client
    mock_conn.key = "authorized-key"
    mock_conn.is_admin = True # Make it admin to bypass session check in handle_bus_message
    
    mock_user = MagicMock()
    mock_user.allowed_types = ["utterance"]
    protocol.db.get_client_by_api_key.return_value = mock_user
    
    payload = {"type": "utterance", "data": {"utterance": "hello"}}
    msg = HiveMessage(HiveMessageType.BUS, payload=payload)
    
    # Mock authorize
    mock_conn.authorize.return_value = True
    
    protocol.handle_message(msg, mock_conn)
    
    # Should be injected into agent bus
    assert protocol.agent_protocol.bus.emit.called
