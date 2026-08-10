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

  "min_protocol_version": 2,

  "min_password_bits": 40,
  "runtime_password_strength_check": true,

  "ping_flood_interval": 30,
  "last_seen_update_interval": 60,

  "presence": {
    "enabled": true,
    "name": "HiveMind-Node",
    "zeroconf": true,
    "upnp": false
  },

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

  "upstream": {
    "enabled": false,
    "host": "127.0.0.1",
    "port": 5678,
    "key": "",
    "password": "",
    "ssl": false,
    "self_signed": true
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

  "utterance_transformers": {},
  "metadata_transformers": {},
  "dialog_transformers": {},

  "policy": {
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
| `min_protocol_version` | int | `2` | Lowest HiveMind protocol version a client may negotiate. The server rejects a client that completes the handshake below this version. It advertises the higher of this value and the version its crypto settings need |
| `min_password_bits` | float | `40` | Lowest password entropy `add-client` accepts, and the handshake backstop rejects |
| `runtime_password_strength_check` | bool | `true` | Re-check password strength at handshake time. Set to `false`, or set `HIVEMIND_DISABLE_PASSWORD_STRENGTH_CHECK=1`, to skip the backstop |
| `last_seen_update_interval` | int | `60` | Seconds to debounce the `last_seen` write, which runs on every inbound message. `0` writes on every message |
| `ping_flood_interval` | int | `30` | Minimum seconds between two mesh-wide `PING` floods emitted by this node. Inside the window the node answers only the peer that pinged it |
| `utterance_transformers` | dict | `{}` | OVOS utterance transformer plugins to load, keyed by plugin name. |
| `metadata_transformers` | dict | `{}` | OVOS metadata transformer plugins to load, keyed by plugin name |
| `dialog_transformers` | dict | `{}` | OVOS dialog transformer plugins to load, keyed by plugin name. They rewrite `QUERY`/`CASCADE` answer chunks before they go back to clients |
| `presence` | dict | see above | Local-network advertisement through the optional `hivemind-presence` package. Keys: `enabled`, `name`, `zeroconf` (mDNS), `upnp` (SSDP) |
| `upstream` | dict | see above | Connection to a master above this node. Disabled by default |

> **`require_crypto` is not a config key.** It is an attribute of
> `HiveMindListenerProtocol` and it defaults to `True`. While it is true, the server
> drops an `INTERCOM` frame that carries no signed envelope: such a frame proves nothing
> about its origin, so the server does not relay it or escalate it. To change the value,
> subclass the protocol or set the attribute on the instance you pass to
> `HiveMindService`.

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

## `upstream`

Connects this node to a master above it. The node keeps serving its own
downstream clients, and it also forwards downstream `PROPAGATE` and `ESCALATE`
up to that master, and fans `BROADCAST` and `PROPAGATE` from the master back
down (HIVEMIND-NODE-1 §3.3 and §4). It is disabled by default, so a node with
no upstream is a top-level master, as before.

```json
"upstream": {
  "enabled": true,
  "host": "master.example.com",
  "port": 5678,
  "key": "the-access-key",
  "password": "the-password",
  "ssl": true,
  "self_signed": false
}
```

| Key | Type | Default | Purpose |
|---|---|---|---|
| `enabled` | bool | `false` | Connect upstream. When `false`, this node is a top-level master |
| `host` | str | `127.0.0.1` | Hostname or IP of the master. Write it without a scheme; `ssl` picks `ws://` or `wss://` |
| `port` | int | `5678` | Port the master listens on |
| `key` | str | `""` | Access key the master issued to this node |
| `password` | str | `""` | Password the master issued to this node |
| `ssl` | bool | `false` | Connect with `wss://` |
| `self_signed` | bool | `true` | Accept a self-signed certificate from the master |

Run `hivemind-core add-client` **on the master** to get the `key` and
`password` for this node. Set both: with either one empty the node logs an
error and stays a top-level master, rather than refusing to start and taking
its own clients offline with it.

The upstream connection keeps its credentials in its own identity file,
`~/.config/hivemind/_identity_upstream.json`. The node's own
`_identity.json` — the identity it presents to its downstream clients — is
never written to by the upstream link.

The connection opens on a background thread and the client keeps retrying, so
an unreachable master delays nothing at startup: the node comes up and serves
its downstream clients while it waits.

You do not have to write the whole block. Any key you leave out keeps its
default from the table above, and a block that is not a block at all (`null`,
say) is replaced by the defaults with a warning. Nothing in the `upstream`
block can keep the node from starting.

Point `upstream` at the master **above** this node, never at this node. An
upstream aimed at one of this node's own listeners is refused at startup, with
an error in the log: the link would connect, be rejected, and reconnect every
few seconds forever. `127.0.0.1` and `0.0.0.0` name the same listener here, so
both are refused.

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
hivemind-core migrate-db --from hivemind-json-db-plugin --to hivemind-sqlite-db-plugin
```

`--from` and `--to` take database plugin entry-point names, not short aliases. The
defaults are the two names shown above.

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
    "password": "s3cr3t",
    "max_connections": 50
  }
}
```

**Use Redis for large deployments.** Redis looks up a client by API key with a single
key read and writes one record at a time. SQLite reads through an `api_key` index and
writes one row. JSON scans every client and rewrites the whole file on each write.

`max_connections` sets the Redis connection pool size. It defaults to 5. Raise it above
the number of clients that handshake at the same time, or the server queues on the pool.

---

## `policy`

Configures the admission-control chain. `MessageTypeACLPolicy` and
`DefaultSessionPolicy` are always prepended and cannot be removed. See [policy.md](policy.md) for the full policy chain specification.

```json
"policy": {
  "chain": [
    {"module": "hivemind-ovos-agent-policy"},
    {"module": "my-quota-policy", "config": {"limit": 500}},
    {"module": "my-experimental-policy", "optional": true}
  ]
}
```

| Field | Type | Purpose |
|---|---|---|
| `module` | str | Entry-point name of the policy plugin |
| `config` | dict | Plugin-specific configuration passed to its constructor |
| `optional` | bool | If `true`, exceptions in `review` log a warning and continue (allow). Default `false` (fail-closed). |

Drop `hivemind-ovos-agent-policy` only if you are running a non-OVOS agent backend.

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

---
[← Architecture](architecture.md) · [Home](README.md) · [CLI Reference →](cli-reference.md)
