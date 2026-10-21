# Plugin Development Guide

Python entry points make HiveMind highly extensible, managed by `hivemind-plugin-manager`.

## Plugin Types

### 1. Network Protocol Plugins

Define how the server listens for connections.

- **Base class**: `hivemind_plugin_manager.protocols.NetworkProtocol`
- **Entry point**: `hivemind.network.protocol`
- **Example implementation**: `hivemind_websocket_protocol.HiveMindWebsocketProtocol`

### 2. Agent Plugins

Define the AI backend that processes intents.

- **Base class**: `hivemind_plugin_manager.protocols.AgentProtocol`
- **Entry point**: `hivemind.agent.protocol`
- **Example implementation**: `ovos_bus_client.hpm.OVOSProtocol`

### 3. Binary Plugins

Define how the server handles raw binary data (for example, audio).

- **Base class**: `hivemind_plugin_manager.protocols.BinaryDataHandlerProtocol`
- **Entry point**: `hivemind.binary.protocol`
- **Example implementation**: `hivemind_audio_binary_protocol.protocol.AudioBinaryProtocol`

### 4. Database Plugins

Define where the server stores client credentials and permissions.

- **Base class**: `hivemind_plugin_manager.database.AbstractDB`
- **Entry point**: `hivemind.database`
- **Example implementation**: `hivemind_sqlite_database.SQLiteDB`

### 5. Policy Plugins

Define admission control: rate limits, quotas, metadata injection, or audit logging.

- **Base class**: `hivemind_plugin_manager.policy.PolicyPlugin`
- **Entry point**: `hivemind.policy`
- **Example implementation**: `hivemind_ovos_agent_plugin.policy.OVOSAgentPolicy`

Add the plugin to the `policy.chain` list in `server.json`. See [Policy Chain](policy.md).

## Example: Creating a Database Plugin

1. Inherit from `hivemind_plugin_manager.database.AbstractDB`.
2. Implement `add_item`, `get_client_by_id`, `get_client_by_api_key`, `search_by_value`, `__iter__`, and `__len__`.
3. Register the entry point in `pyproject.toml`:

```toml
[project.entry-points."hivemind.database"]
my-db = "my_package.db:MyDatabasePlugin"
```

Once installed, the server can use it by setting `"module": "my-db"` in its `server.json` configuration.

---
[← CLI Reference](cli.md) · [Home](index.md) · [Network Map →](hive_map.md)
