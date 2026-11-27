# Install and run a hub
<!-- agent-hint
covers: how to install hivemind-core, start the hub and read its log
source: pyproject.toml, hivemind_core/scripts.py:listen, hivemind_core/service.py:HiveMindService.run, hivemind_core/config.py:get_server_config
generated: no
verify: for c in $(grep -o '^ *hivemind-core [a-z][a-z-]*' docs/install-and-run.md | awk '{print $2}' | sort -u); do hivemind-core $c --help >/dev/null 2>&1 || exit 1; done
see: clients.md
-->

This page installs the hub, gives it one client and starts it. At the end, the hub listens for satellites on port 5678.

## Example

```bash
uv venv
uv pip install --prerelease=allow hivemind-core
hivemind-core add-client --name kitchen --allow ovos.utterance.handle --allow recognizer_loop:utterance
hivemind-core listen
```

The `listen` command prints nothing to the terminal. It writes its log to `~/.local/state/mycroft/hivemind.log`. A start writes these lines, with others between them:

```text
hivemind_core.service:on_started - INFO - hivemind-core service started!
hivemind_core.service:run - INFO - Agent protocol: OVOSAgentProtocol
hivemind_core.service:run - INFO - BinaryData protocol: BinaryDataHandlerProtocol
hivemind_core.policy:from_config - INFO - loaded policy plugin: hivemind-ovos-agent-policy
hivemind_core.service:run - INFO - Network protocol: HiveMindWebsocketProtocol
hivemind_core.service:on_ready - INFO - hivemind-core service ready!
hivemind_websocket_protocol:start_listener - INFO - ws listener started
```

## Steps

1. Install the package. The hub needs Python 3.10 or later. Install with `--prerelease=allow`, because the package and its dependencies publish alpha releases.

   ```bash
   uv pip install --prerelease=allow hivemind-core
   ```

2. Start the agent behind the hub. The default agent plugin, `hivemind-ovos-agent-plugin`, connects to an OpenVoiceOS message bus at `127.0.0.1:8181`. Start OpenVoiceOS first, or set another agent in `agent_protocol` (see [Configuration](configuration.md)).

3. Add one client. The command prints the access key and the password. Give both to the satellite. [Clients](clients.md) explains each field.

4. Start the hub.

   ```bash
   hivemind-core listen
   ```

   On the first run, the hub writes `~/.config/hivemind-core/server.json` with the defaults. It enables only the network transports that are installed. With only the dependencies of `hivemind-core`, that is the WebSocket transport on `0.0.0.0:5678`.

5. Look at the configuration that the hub uses:

   ```bash
   hivemind-core print-config
   ```

6. To stop the hub, press Ctrl+C. The log shows `hivemind-core is shutting down...`.

## Optional packages

| Extra or package | What it adds |
| :--- | :--- |
| `hivemind-core[presence]` | `hivemind-presence` and `hivemind-ggwave`: local network discovery (`presence` block) |
| `hivemind-http-protocol` | the HTTP transport `hivemind-http-plugin`, port 5679 by default |
| `hivemind-rendezvous` | the store-and-forward mailbox (`rendezvous` block) |

## Several hubs on one machine

Each hub needs its own `XDG_CONFIG_HOME` and `XDG_DATA_HOME`, because these hold the configuration, the client database and the node identity (`hivemind/_identity.json`). Give each hub a free port for each transport. The `agent_protocol` port selects the OpenVoiceOS instance that the hub uses. When all transports stop, the log says `Every network protocol has stopped, this node no longer accepts clients`.

## Files

| Path | Contents |
| :--- | :--- |
| `~/.config/hivemind-core/server.json` | hub configuration |
| `~/.local/share/hivemind-core/clients.db` | client database, SQLite backend |
| `~/.local/share/hivemind-core/clients.json` | client database, JSON backend |
| `~/.local/state/mycroft/hivemind.log` | log of `hivemind-core` commands and of `listen` |

The paths follow the XDG variables `XDG_CONFIG_HOME`, `XDG_DATA_HOME` and `XDG_STATE_HOME`.

---
[Home](index.md) · [Clients →](clients.md)
