# Plugins
<!-- agent-hint
covers: the four plugin types of the hub (network, agent, binary, database), how to list, install and select them
source: hivemind_core/service.py:get_agent_protocol, hivemind_core/service.py:get_binary_protocol, hivemind_core/service.py:HiveMindService.run, hivemind_core/database.py, hivemind_core/config.py:_DEFAULT
generated: no
verify: python3 -c "import sys; from hivemind_plugin_manager import HiveMindPluginTypes as T; doc=open('docs/plugins.md').read(); sys.exit(0 if all(t.value in doc for t in T) else 1)"
see: troubleshooting.md
-->

The hub has no transport, agent or storage of its own. Plugins supply each of them. This page shows how to list the installed plugins and how to select one in `server.json`.

## Example

This script lists the plugins that are installed, for each entry point group:

```python
from hivemind_plugin_manager import HiveMindPluginTypes, find_plugins

for plugin_type in HiveMindPluginTypes:
    print(plugin_type.value, sorted(find_plugins(plugin_type)))
```

With only the dependencies of `hivemind-core`, it prints:

```text
hivemind.database ['hivemind-json-db-plugin', 'hivemind-sqlite-db-plugin']
hivemind.network.protocol ['hivemind-websocket-plugin']
hivemind.agent.protocol ['hivemind-ovos-agent-plugin']
hivemind.binary.protocol []
hivemind.policy ['hivemind-deny-all-policy', 'hivemind-message-type-acl-policy', 'hivemind-ovos-agent-policy']
```

## Steps

1. Install the plugin package in the environment of the hub, for example `uv pip install --prerelease=allow hivemind-http-protocol`.
2. Run the script above and find the entry point name of the plugin.
3. Put the name in the `server.json` block of its type (see the table below).
4. Restart the hub. The log names each plugin that loads, for example `Network protocol: HiveMindWebsocketProtocol`.

## Reference

| Type | Entry point group | `server.json` block | Default |
| :--- | :--- | :--- | :--- |
| Network | `hivemind.network.protocol` | `network_protocol` | `hivemind-websocket-plugin` |
| Agent | `hivemind.agent.protocol` | `agent_protocol` | `hivemind-ovos-agent-plugin` |
| Binary | `hivemind.binary.protocol` | `binary_protocol` | none |
| Database | `hivemind.database` | `database` | `hivemind-sqlite-db-plugin` |
| Policy | `hivemind.policy` | `policy.chain` | `hivemind-ovos-agent-policy` |

### Network plugins

A network plugin listens for clients and carries HiveMind messages. The hub can run more than one at a time: each key of `network_protocol` starts one transport, with the key value as its settings.

```json
"network_protocol": {
  "hivemind-websocket-plugin": {"host": "0.0.0.0", "port": 5678},
  "hivemind-http-plugin": {"host": "0.0.0.0", "port": 5679}
}
```

| Package | Entry point name |
| :--- | :--- |
| `hivemind-websocket-protocol` (dependency of the hub) | `hivemind-websocket-plugin` |
| `hivemind-http-protocol` | `hivemind-http-plugin` |

### Agent plugins

The agent plugin receives the messages that pass the policy chain and sends the answers back. The hub runs one agent. `module` names it, and the key with the same name holds its settings:

```json
"agent_protocol": {
  "module": "hivemind-ovos-agent-plugin",
  "hivemind-ovos-agent-plugin": {"host": "127.0.0.1", "port": 8181}
}
```

`hivemind-ovos-agent-plugin` connects to an OpenVoiceOS message bus. Other agent packages, such as `hivemind-persona-agent-plugin`, document their own settings. With an agent that is not OpenVoiceOS, remove `hivemind-ovos-agent-policy` from `policy.chain`.

### Binary plugins

A binary plugin handles binary payloads from clients, for example audio. With `"module": null`, the hub uses `BinaryDataHandlerProtocol`, which does nothing with the payloads. Satellites that stream audio need a binary plugin such as `hivemind-audio-binary-protocol`:

```json
"binary_protocol": {
  "module": "hivemind-audio-binary-protocol-plugin",
  "hivemind-audio-binary-protocol-plugin": {}
}
```

Binary payloads also pass the policy chain. A client with an empty `allowed_types` list cannot send them.

### Database plugins

A database plugin stores the client rows. The `hivemind-core` CLI and the hub read the same `database` block.

| Package | Entry point name |
| :--- | :--- |
| `hivemind-sqlite-database` (dependency of the hub) | `hivemind-sqlite-db-plugin` |
| `hivemind-json-db-plugin` (dependency of the hub) | `hivemind-json-db-plugin` |
| `hivemind-redis-database` | `hivemind-redis-db-plugin` |

To change the backend, copy the clients first, then change `database.module`:

```bash
hivemind-core migrate-db --from hivemind-json-db-plugin --to hivemind-sqlite-db-plugin
```

## Write a plugin

A plugin is a Python package that subclasses one base class from `hivemind_plugin_manager` and registers the subclass under one entry-point group in its `pyproject.toml`.

| Type | Base class | Methods to implement | Entry-point group | Guide |
| :--- | :--- | :--- | :--- | :--- |
| Network | `hivemind_plugin_manager.protocols.NetworkProtocol` | `run` | `hivemind.network.protocol` | [network-protocol.md](https://github.com/JarbasHiveMind/hivemind-plugin-manager/blob/dev/docs/plugins/network-protocol.md) |
| Agent | `hivemind_plugin_manager.protocols.AgentProtocol` | `natural_language_query` | `hivemind.agent.protocol` | [agent-protocol.md](https://github.com/JarbasHiveMind/hivemind-plugin-manager/blob/dev/docs/plugins/agent-protocol.md) |
| Binary | `hivemind_plugin_manager.protocols.BinaryDataHandlerProtocol` | the `handle_*` methods for the binary types that the plugin accepts | `hivemind.binary.protocol` | [binary-protocol.md](https://github.com/JarbasHiveMind/hivemind-plugin-manager/blob/dev/docs/plugins/binary-protocol.md) |
| Database | `hivemind_plugin_manager.database.AbstractDB` | `add_item`, `search_by_value`, `__len__`, `__iter__` | `hivemind.database` | [database.md](https://github.com/JarbasHiveMind/hivemind-plugin-manager/blob/dev/docs/plugins/database.md) |
| Policy | `hivemind_plugin_manager.policy.PolicyPlugin` | `review` | `hivemind.policy` | [policies.md](policies.md) |

Example registration for a network plugin:

```toml
[project.entry-points."hivemind.network.protocol"]
my-network-plugin = "my_package:MyNetworkProtocol"
```

The entry-point name is the plugin name that `server.json` uses.

---
[← Policies and ACLs](policies.md) · [Home](index.md) · [Troubleshooting →](troubleshooting.md)
