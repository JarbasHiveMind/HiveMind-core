# Configuration Reference

HiveMind Core reads its configuration from `~/.config/hivemind-core/server.json` (XDG).
The file is created with defaults on first run if absent.

---

## Full Default Configuration

```json
{
  "binarize": false,
  "allowed_encodings": [
    "JSON-B64", "JSON-URLSAFE-B64", "JSON-B91",
    "JSON-Z85B", "JSON-Z85P", "JSON-B32", "JSON-HEX"
  ],
  "allowed_ciphers": ["CHACHA20-POLY1305", "AES-GCM"],

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
      "port": 5678,
      "ssl": false,
      "cert_dir": "~/.local/share/hivemind",
      "cert_name": "hivemind"
    },
    "hivemind-http-plugin": {
      "host": "0.0.0.0",
      "port": 5679,
      "ssl": false,
      "cert_dir": "~/.local/share/hivemind",
      "cert_name": "hivemind"
    }
  },

  "database": {
    "module": "hivemind-sqlite-db-plugin",
    "hivemind-sqlite-db-plugin": {
      "name": "clients",
      "subfolder": "hivemind-core"
    }
  },

  "policy": {
    "warn_review_ms": null,
    "max_review_ms": null,
    "busy_retry_after_ms": 250,
    "chain": [
      {"module": "hivemind-ovos-agent-policy"}
    ]
  }
}
```

---

## Top-Level Keys

| Key | Type | Default | Purpose |
|---|---|---|---|
| `binarize` | bool | `false` | Enable HiveMind binarization protocol (requires compatible client version) |
| `allowed_encodings` | list | see above | Ordered list of accepted message encodings; first match wins during handshake |
| `allowed_ciphers` | list | `["CHACHA20-POLY1305", "AES-GCM"]` | Accepted session ciphers; first match wins |

---

## `agent_protocol`

Selects the AI backend. `module` is the entry-point name of an agent protocol plugin.

```json
"agent_protocol": {
  "module": "hivemind-ovos-agent-plugin",
  "hivemind-ovos-agent-plugin": {
    "host": "127.0.0.1",
    "port": 8181
  }
}
```

The plugin-specific config object is keyed by the plugin name. Available plugins:

| Plugin name | Package | Backend |
|---|---|---|
| `hivemind-ovos-agent-plugin` | `ovos-bus-client` | OpenVoiceOS message bus |
| `hivemind-persona-agent-plugin` | `ovos-persona` | Persona / LLM (OpenAI-compatible) |

---

## `binary_protocol`

Optional server-side audio/image handler. Set `module` to `null` to use the no-op stub.

```json
"binary_protocol": {
  "module": "hivemind-audio-binary-protocol-plugin"
}
```

The `hivemind-audio-binary-protocol` plugin enables server-side STT and TTS, used by
lightweight satellites (voice relay, mic satellite) that stream raw audio instead of
running a local speech stack.

---

## `network_protocol`

Each key is a network plugin name; its value is passed to the plugin's constructor.
Multiple plugins run simultaneously (e.g. WebSocket + HTTP).

| Plugin name | Package | Default port |
|---|---|---|
| `hivemind-websocket-plugin` | `hivemind-websocket-protocol` | 5678 |
| `hivemind-http-plugin` | `hivemind-http-protocol` | 5679 |

**TLS example** (generate a self-signed cert first):

```json
"hivemind-websocket-plugin": {
  "host": "0.0.0.0",
  "port": 5678,
  "ssl": true,
  "cert_dir": "/etc/hivemind/certs",
  "cert_name": "hivemind"
}
```

---

## `database`

Selects the client credential store. `module` is the entry-point name.

```json
"database": {
  "module": "hivemind-sqlite-db-plugin",
  "hivemind-sqlite-db-plugin": {
    "name": "clients",
    "subfolder": "hivemind-core"
  }
}
```

**Default for fresh installs:** SQLite. An existing `clients.json` on disk keeps using the
JSON backend automatically. Migrate with:

```bash
hivemind-core migrate-db --to sqlite
```

Available backends:

| Plugin name | Package | Type |
|---|---|---|
| `hivemind-sqlite-db-plugin` | `hivemind-sqlite-database` | Local SQLite |
| `hivemind-json-db-plugin` | `json_database` | Local JSON file |
| `hivemind-redis-db-plugin` | `hivemind-redis-database` | Remote Redis |

**Redis example:**

```json
"database": {
  "module": "hivemind-redis-db-plugin",
  "hivemind-redis-db-plugin": {
    "name": "clients",
    "subfolder": "hivemind-core",
    "host": "192.168.1.10",
    "port": 6379,
    "password": "s3cr3t"
  }
}
```

---

## `policy`

Configures the admission-control chain. `MessageTypeACLPolicy` is always prepended and
cannot be removed. See [policy.md](policy.md) for the full policy chain specification.

```json
"policy": {
  "warn_review_ms": 100,
  "max_review_ms": 250,
  "busy_retry_after_ms": 500,
  "chain": [
    {"module": "hivemind-ovos-agent-policy"},
    {"module": "my-quota-policy", "config": {"limit": 500}},
    {"module": "my-experimental-policy", "optional": true}
  ]
}
```

| Field | Type | Purpose |
|---|---|---|
| `warn_review_ms` | number/null | Optional warning threshold for total policy review time. Logs slow admission but does not deny. Default `null`. |
| `max_review_ms` | number/null | Optional maximum total policy review budget. When exceeded after a policy hook returns, the chain returns retryable `policy_busy` instead of continuing to admit the message. Default `null`. |
| `busy_retry_after_ms` | int/null | Optional retry hint included in `policy_busy.data.retry_after_ms`. Default `250`; only used when `max_review_ms` is set. |
| `module` | str | Entry-point name of the policy plugin |
| `config` | dict | Plugin-specific configuration passed to its constructor |
| `optional` | bool | If `true`, exceptions in `review` log a warning and continue (allow). Default `false` (fail-closed). |

Drop `hivemind-ovos-agent-policy` only if you are running a non-OVOS agent backend.

The timing fields are admission guardrails, not hard kill switches. Policy
hooks are synchronous; HiveMind checks elapsed time after each policy returns.
Use `warn_review_ms` first to learn normal review latency, then set
`max_review_ms` if overloaded clients should receive a retryable
`policy_busy` denial instead of waiting until their own timeout. See
[policy.md](policy.md#admission-timing-budget) for the exact wire format.

---

## Editing the Config

The file is a plain JSON document. After editing, restart hivemind-core for changes to
take effect:

```bash
hivemind-core listen
```

The `hpm` CLI from `hivemind-plugin-manager` provides a friendlier interface for
switching active plugins:

```bash
hpm list database
hpm set database hivemind-redis-db-plugin
hpm show-config
```
