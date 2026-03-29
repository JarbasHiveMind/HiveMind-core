# Plugin System

HiveMind Core delegates all transport, AI, binary handling, and storage concerns to plugins. Plugins are discovered via Python entry points managed by `hivemind-plugin-manager`.

## Network protocol plugins

Responsible for accepting connections and delivering raw payloads to `HiveMindListenerProtocol`.

| Plugin | Description | Install |
|---|---|---|
| `hivemind-websocket-protocol` | WebSocket-based real-time connections | `pip install hivemind-websocket-protocol` |
| `hivemind-http-protocol` | HTTP request/response, for clients without persistent connections | `pip install hivemind-http-protocol` |

Multiple network protocols can run simultaneously — each is started in its own daemon thread.

Configuration example (in `server.json`):

```json
"network_protocol": {
  "hivemind-websocket-plugin": { "host": "0.0.0.0", "port": 5678 },
  "hivemind-http-plugin":      { "host": "0.0.0.0", "port": 5679 }
}
```

---

## Agent protocol plugins

Responsible for handling the `Message` payloads extracted from `HiveMessageType.BUS` messages.

| Plugin | Description | Install |
|---|---|---|
| `hivemind-ovos-agent-plugin` | Forwards messages to a running OVOS / Mycroft message bus | via `ovos-bus-client` |
| `hivemind-persona-agent-plugin` | Routes messages to an LLM persona (OpenAI-compatible) | via `ovos-persona` |

Only one agent protocol can be active at a time.

Configuration example:

```json
"agent_protocol": {
  "module": "hivemind-ovos-agent-plugin",
  "hivemind-ovos-agent-plugin": { "host": "127.0.0.1", "port": 8181 }
}
```

---

## Binary data protocol plugins

Optional. Invoked when a `HiveMessageType.BINARY` message is received.

| Plugin | Description | Install |
|---|---|---|
| `hivemind-audio-binary-protocol` | STT transcription and audio handling via `ovos-plugin-manager` | `pip install hivemind-audio-binary-protocol` |

When no binary protocol is configured (`"module": null`), binary messages are silently ignored.

Binary payload types dispatched to the plugin:

| `HiveMindBinaryPayloadType` | Handler called |
|---|---|
| `RAW_AUDIO` | `handle_microphone_input(data, sample_rate, sample_width, client)` |
| `STT_AUDIO_TRANSCRIBE` | `handle_stt_transcribe_request(data, sr, sw, lang, client)` |
| `STT_AUDIO_HANDLE` | `handle_stt_handle_request(data, sr, sw, lang, client)` |
| `TTS_AUDIO` | `handle_receive_tts(data, utterance, lang, file_name, client)` |
| `FILE` | `handle_receive_file(data, file_name, client)` |
| `NUMPY_IMAGE` | `handle_numpy_image(data, camera_id, client)` |

---

## Database plugins

| Plugin | Description | Install |
|---|---|---|
| `hivemind-json-db-plugin` | JSON flat-file storage (default) | bundled |
| `hivemind-sqlite-database` | SQLite storage for production deployments | `pip install hivemind-sqlite-database` |
| `hivemind-redis-database` | Redis storage for distributed deployments | `pip install hivemind-redis-database` |

Configuration example:

```json
"database": {
  "module": "hivemind-sqlite-database",
  "hivemind-sqlite-database": { "path": "~/.local/share/hivemind/clients.db" }
}
```

---

## Writing a custom plugin

All plugin types follow the same pattern:

1. Create a class that inherits from the appropriate base class in `hivemind-plugin-manager`.
2. Register it via a Python entry point in your `setup.py` / `pyproject.toml`.
3. Reference the entry-point name in `server.json`.

The four base classes are:

| Base class | Module |
|---|---|
| `NetworkProtocol` | `hivemind_plugin_manager.protocols` |
| `AgentProtocol` | `hivemind_plugin_manager.protocols` |
| `BinaryDataHandlerProtocol` | `hivemind_plugin_manager.protocols` |
| `AbstractDB` | `hivemind_plugin_manager.database` |
