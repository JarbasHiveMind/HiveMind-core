# Configuration

The server configuration file is located at:

```
~/.config/hivemind-core/server.json
```

If the file does not exist, HiveMind Core uses built-in defaults.

## Default configuration

```json
{
  "agent_protocol": {
    "module": "hivemind-ovos-agent-plugin",
    "hivemind-ovos-agent-plugin": {
      "host": "127.0.0.1",
      "port": 8181
    }
  },
  "binary_protocol": {
    "module": null
  },
  "network_protocol": {
    "hivemind-websocket-plugin": {
      "host": "0.0.0.0",
      "port": 5678
    },
    "hivemind-http-plugin": {
      "host": "0.0.0.0",
      "port": 5679
    }
  },
  "database": {
    "module": "hivemind-json-db-plugin",
    "hivemind-json-db-plugin": {
      "name": "clients",
      "subfolder": "hivemind-core"
    }
  }
}
```

## Sections

### `agent_protocol`

Controls which AI backend handles incoming messages.

| Key | Type | Description |
|---|---|---|
| `module` | `str` | Plugin entry-point name (e.g. `"hivemind-ovos-agent-plugin"`) |
| `<module>` | `dict` | Plugin-specific config passed to the plugin constructor |

**OVOS agent example** — connects to an OVOS message bus running on the same machine:

```json
"agent_protocol": {
  "module": "hivemind-ovos-agent-plugin",
  "hivemind-ovos-agent-plugin": {
    "host": "127.0.0.1",
    "port": 8181
  }
}
```

**Persona (LLM) example**:

```json
"agent_protocol": {
  "module": "hivemind-persona-agent-plugin",
  "hivemind-persona-agent-plugin": {
    "persona": "my-persona-name"
  }
}
```

---

### `binary_protocol`

Optional. Controls what to do with binary payloads (raw audio, images, files).

Set `module` to `null` to disable binary handling (default). When enabled, binary data is dispatched to the plugin based on the `HiveMindBinaryPayloadType` of the message.

```json
"binary_protocol": {
  "module": "hivemind-audio-binary-protocol",
  "hivemind-audio-binary-protocol": {}
}
```

---

### `network_protocol`

A dict of `{ plugin_name: plugin_config }` pairs. Multiple network protocols can run simultaneously.

```json
"network_protocol": {
  "hivemind-websocket-plugin": {
    "host": "0.0.0.0",
    "port": 5678
  }
}
```

Common plugin options:

| Key | Type | Description |
|---|---|---|
| `host` | `str` | Bind address (use `"0.0.0.0"` for all interfaces) |
| `port` | `int` | Listen port |

---

### `database`

Controls where client credentials are persisted.

| Key | Type | Description |
|---|---|---|
| `module` | `str` | Plugin entry-point name |
| `<module>` | `dict` | Plugin-specific configuration |

**JSON backend** (default, zero-dependency):

```json
"database": {
  "module": "hivemind-json-db-plugin",
  "hivemind-json-db-plugin": {
    "name": "clients",
    "subfolder": "hivemind-core"
  }
}
```

**SQLite backend**:

```json
"database": {
  "module": "hivemind-sqlite-database",
  "hivemind-sqlite-database": {
    "path": "~/.local/share/hivemind/clients.db"
  }
}
```

**Redis backend**:

```json
"database": {
  "module": "hivemind-redis-database",
  "hivemind-redis-database": {
    "host": "localhost",
    "port": 6379
  }
}
```

---

### Encryption options (optional)

Additional top-level keys control encryption negotiation:

| Key | Type | Default | Description |
|---|---|---|---|
| `binarize` | `bool` | `false` | Offer binary serialisation to connecting clients |
| `allowed_ciphers` | `list[str]` | `["aes-gcm"]` | Cipher suites accepted during handshake |
| `allowed_encodings` | `list[str]` | all | Encoding schemes accepted during handshake |

---

## Inspect current configuration

```bash
hivemind-core print-config
```
