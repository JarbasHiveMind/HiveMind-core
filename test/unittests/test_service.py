import pytest
from unittest.mock import MagicMock, patch
from hivemind_core.service import HiveMindService

@pytest.fixture
def mock_service_config():
    return {
        "agent_protocol": {"module": "mock_agent"},
        "binary_protocol": {"module": "mock_binary"},
        "network_protocol": {"mock_net": {"port": 1234}},
        "presence": {"enabled": False},
        "database": {"module": "hivemind-json-db-plugin"} # Add database config
    }

def test_service_init():
    with patch("hivemind_core.service.get_server_config") as mock_cfg:
        mock_cfg.return_value = {"database": {"module": "hivemind-json-db-plugin"}}
        service = HiveMindService()
        assert service._status is not None
        assert service._status.name == "HiveMind"

def test_service_hooks():
    ready_mock = MagicMock()
    with patch("hivemind_core.service.get_server_config") as mock_cfg:
        mock_cfg.return_value = {"database": {"module": "hivemind-json-db-plugin"}}
        service = HiveMindService(ready_hook=ready_mock)
        service.ready_hook()
        ready_mock.assert_called_once()

@patch("hivemind_core.service.get_agent_protocol")
@patch("hivemind_core.service.get_binary_protocol")
@patch("hivemind_core.service.NetworkProtocolFactory")
@patch("hivemind_core.service.get_server_config")
@patch("hivemind_core.service.create_daemon")
@patch("hivemind_core.service.wait_for_exit_signal")
@patch("hivemind_core.service.ClientDatabase") # Mock DB during run
def test_service_run(mock_db, mock_wait, mock_daemon, mock_cfg, mock_net_factory, mock_bin, mock_agent, mock_service_config):
    mock_cfg.return_value = mock_service_config
    
    # Mock Agent Protocol
    mock_agent_class = MagicMock()
    mock_agent_class.__name__ = "MockAgent"
    mock_agent.return_value = (mock_agent_class, {})
    
    # Mock Binary Protocol
    mock_bin_class = MagicMock()
    mock_bin_class.__name__ = "MockBinary"
    mock_bin.return_value = (mock_bin_class, {})
    
    # Mock Network Protocol
    mock_net_class = MagicMock()
    mock_net_class.__name__ = "MockNet"
    mock_net_factory.get_class.return_value = mock_net_class
    
    service = HiveMindService()
    service.run()
    
    # Verify network protocols were started
    mock_daemon.assert_called()
