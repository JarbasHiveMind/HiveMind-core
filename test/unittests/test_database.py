import pytest
from unittest.mock import MagicMock, patch
from hivemind_core.database import ClientDatabase
from hivemind_plugin_manager.database import Client

@pytest.fixture
def mock_db_config():
    return {
        "module": "hivemind-json-db-plugin",
        "hivemind-json-db-plugin": {
            "name": "hivemind-test"
        }
    }

@pytest.fixture
def client_database(mock_db_config):
    with patch("hivemind_core.database.get_server_config") as mock_cfg:
        mock_cfg.return_value = {"database": mock_db_config}
        db = ClientDatabase()
        yield db

def test_client_database_init(client_database):
    assert client_database.db is not None
    # Verify it loaded the json_database plugin
    assert client_database.db.__class__.__name__ == "JsonDB"

def test_add_get_client(client_database):
    api_key = "test-key"
    name = "Test Node"
    
    # Add client
    success = client_database.add_client(name=name, key=api_key)
    assert success is True
    
    # Get client
    client = client_database.get_client_by_api_key(api_key)
    assert client is not None
    assert client.name == name
    assert client.api_key == api_key

def test_update_client(client_database):
    api_key = "update-key"
    client_database.add_client(name="Old Name", key=api_key)
    
    # Update
    success = client_database.add_client(name="New Name", key=api_key, admin=True)
    assert success is True
    
    client = client_database.get_client_by_api_key(api_key)
    assert client.name == "New Name"
    assert client.is_admin is True

def test_delete_client(client_database):
    api_key = "delete-key"
    client_database.add_client(name="To Delete", key=api_key)
    
    success = client_database.delete_client(api_key)
    assert success is True
    
    assert client_database.get_client_by_api_key(api_key) is None

def test_get_clients_by_name(client_database):
    client_database.add_client(name="Shared Name", key="key1")
    client_database.add_client(name="Shared Name", key="key2")
    client_database.add_client(name="Unique Name", key="key3")
    
    clients = client_database.get_clients_by_name("Shared Name")
    assert len(clients) == 2
