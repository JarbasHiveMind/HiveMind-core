# Plugin Development Guide

HiveMind is highly extensible via Python entry points, managed by the `hivemind-plugin-manager`.

## Plugin Types

### 1. Network Protocol Plugins
Define how the Mind listens for connections.
- **Base Class**: `hivemind_plugin_manager.protocols.NetworkProtocol`
- **Entry Point**: `hivemind.network.protocol`
- **Example Implementation**: `hivemind_websocket_protocol.HiveMindWebsocketProtocol`

### 2. Agent Plugins
Define the AI backend that processes intents.
- **Base Class**: `hivemind_plugin_manager.protocols.AgentProtocol`
- **Entry Point**: `hivemind.agent.protocol`
- **Example Implementation**: `ovos_bus_client.hpm.OVOSProtocol`

### 3. Binary Plugins
Define how raw binary data (e.g., audio) is handled.
- **Base Class**: `hivemind_plugin_manager.protocols.BinaryDataHandlerProtocol`
- **Entry Point**: `hivemind.binary.protocol`
- **Example Implementation**: `hivemind_audio_binary_protocol.protocol.AudioBinaryProtocol`

### 4. Database Plugins
Define where client credentials and permissions are stored.
- **Base Class**: `hivemind_plugin_manager.database.AbstractDB`
- **Entry Point**: `hivemind.database`
- **Example Implementation**: `hivemind_sqlite_database.SQLiteDB`

## Example: Creating a Database Plugin

1. Inherit from `hivemind_plugin_manager.database.AbstractDB`.
2. Implement methods like `add_client`, `get_client`, and `list_clients`.
3. Register the entry point in `setup.py`:
```python
entry_points={
    'hivemind.database': [
        'my-db = my_package.db:MyDatabasePlugin'
    ]
}
```
Once installed, the Mind can use it by setting `"module": "my-db"` in its `server.json` configuration.
