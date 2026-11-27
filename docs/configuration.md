# Configuration reference
<!-- agent-hint
covers: every key of server.json, its default and its effect
source: hivemind_core/config.py:_DEFAULT, hivemind_core/config.py:_default_database, hivemind_core/config.py:get_server_config
generated: no
verify: python3 -c "import re,sys; from hivemind_core.config import _DEFAULT; doc=open('docs/configuration.md').read().split('\n### Top-level keys\n')[1].split('\n### Handshake')[0]; keys=set(re.findall(r'^\| \`([a-z_]+)\`', doc, re.M)); want=set(_DEFAULT)|{'database'}; sys.exit(0 if keys==want else 1)"
see: security.md
-->

The hub reads one JSON file, `~/.config/hivemind-core/server.json`. This page lists each top-level key with its default value. The defaults are in `hivemind_core/config.py`.

## Example

This `server.json` changes the WebSocket port and lowers the rate limit for each access key. The hub adds the default value of each key that the file does not set.

```json
{
  "network_protocol": {
    "hivemind-websocket-plugin": {
      "host": "0.0.0.0",
      "port": 5700
    }
  },
  "handshake_failures_per_key": 3
}
```

To see the result, run `hivemind-core print-config`.

## Steps

1. Stop the hub.
2. Edit `~/.config/hivemind-core/server.json`. The file can hold comments.
3. Run `hivemind-core print-config` to make sure that the hub reads the file.
4. Start the hub with `hivemind-core listen`.

## How the hub reads the file

- When the file does not exist, the hub writes it with the defaults. In `network_protocol`, it writes only the transports that are installed.
- When the file is not valid JSON, or is not a JSON object, each command stops with an error. The hub does not change the file. Fix the file, or remove it to start from the defaults.
- A top-level key that the file does not set gets its default value.
- In a block that names a `module` (`agent_protocol`, `binary_protocol`, `database`), a missing sub-key gets its default value. In `network_protocol`, the sub-keys are the set of transports that start, so the hub adds no transport.
- The `upstream` block always gets each sub-key that it does not set.
- The hub ignores `policy.fail_open` and writes a warning to the log. The policy chain always fails closed.

## Reference

### Top-level keys

| Key | Default | Effect |
| :--- | :--- | :--- |
| `binarize` | `false` | offer the binary framing of HiveMind messages |
| `allowed_encodings` | `["JSON-B64", "JSON-URLSAFE-B64", "JSON-B91", "JSON-Z85B", "JSON-Z85P", "JSON-B32", "JSON-HEX"]` | payload encodings that the hub offers in the HANDSHAKE, in order of preference |
| `allowed_ciphers` | `["CHACHA20-POLY1305", "AES-GCM"]` | ciphers that the hub offers in the HANDSHAKE |
| `min_password_bits` | `40` | the minimum guess resistance of a client password, in bits |
| `runtime_password_strength_check` | `true` | check the password again at each handshake |
| `agent_protocol` | `{"module": "hivemind-ovos-agent-plugin", "hivemind-ovos-agent-plugin": {"host": "127.0.0.1", "port": 8181}}` | the agent that receives the client messages |
| `binary_protocol` | `{"module": null}` | the handler for binary payloads; `null` writes each payload to the log only |
| `network_protocol` | see [Transports](#transports) | the transports that listen for clients |
| `database` | see [Database](#database) | the client database backend |
| `presence` | `{"enabled": true, "name": "HiveMind-Node", "zeroconf": true, "upnp": false}` | local network discovery; needs the `presence` extra |
| `rendezvous` | `{"enabled": false, "max_pending_per_mailbox": 256}` | hold messages for peers that are not online at the same time; needs `hivemind-rendezvous` |
| `upstream` | see [Upstream](#upstream) | a connection from this hub to a hub above it |
| `policy` | `{"chain": [{"module": "hivemind-ovos-agent-policy"}]}` | policy plugins after the built-in gates; see [Policies and ACLs](policies.md) |
| `utterance_transformers` | `{}` | OVOS utterance transformer plugins for client utterances |
| `metadata_transformers` | `{}` | OVOS metadata transformer plugins for client messages |
| `dialog_transformers` | `{}` | OVOS dialog transformer plugins for QUERY and CASCADE answers |
| `ping_flood_interval` | `30` | minimum seconds between two PING floods that this hub sends to the mesh |
| `last_seen_update_interval` | `60` | minimum seconds between two writes of the `last_seen` time of one client; `0` writes on each message |
| `handshake_failures_per_key` | `5` | failed handshakes for one access key, inside the window, that block that key; `0` turns the limit off |
| `handshake_failures_per_ip` | `20` | failed handshakes from one source IP, inside the window, that block that IP; `0` turns the limit off |
| `handshake_failure_window` | `60` | the length of the window for the two limits above, in seconds |

The `HIVEMIND_DISABLE_PASSWORD_STRENGTH_CHECK=1` environment variable also turns off the check at the handshake. The check at `add-client` always applies.

A transformer plugin loads only when its name is a key of its block, for example `"utterance_transformers": {"ovos-utterance-corrections-plugin": {}}`.

### Handshake rate limit

The hub counts failed handshakes for each access key and for each source IP. When a count reaches its limit inside `handshake_failure_window`, the hub refuses each handshake from that key or that IP until the oldest failure leaves the window. A successful handshake does not reset a count. The two limits must be non-negative integers. The hub refuses other values with a `ValueError`. [Security model](security.md#handshake-rate-limit) explains the defence.

### Transports

`network_protocol` maps each transport name to its settings. Each name in the block starts one transport.

| Transport | `host` | `port` | `ssl` | `cert_dir` | `cert_name` |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `hivemind-websocket-plugin` | `0.0.0.0` | `5678` | `false` | `~/.local/share/hivemind` | `hivemind` |
| `hivemind-http-plugin` | `0.0.0.0` | `5679` | `false` | `~/.local/share/hivemind` | `hivemind` |

`hivemind-http-plugin` needs the `hivemind-http-protocol` package. When a transport in the block is not installed, the log names the package to install, and the other transports start. When no transport starts, the hub stops.

### Database

A fresh install uses SQLite:

```json
"database": {
  "module": "hivemind-sqlite-db-plugin",
  "hivemind-sqlite-db-plugin": {"name": "clients", "subfolder": "hivemind-core"}
}
```

When `~/.local/share/hivemind-core/clients.json` exists and `clients.db` does not, the default is `hivemind-json-db-plugin` with the same settings. To move the clients to SQLite, run `hivemind-core migrate-db --to hivemind-sqlite-db-plugin`, then set `database.module`.

### Upstream

| Sub-key | Default | Effect |
| :--- | :--- | :--- |
| `enabled` | `false` | connect to a hub above this one |
| `host` | `127.0.0.1` | the host of the upper hub |
| `port` | `5678` | the port of the upper hub |
| `key` | `""` | the access key that the upper hub gave to this hub |
| `password` | `""` | the password that the upper hub gave to this hub |
| `ssl` | `false` | use `wss://` instead of `ws://` |
| `self_signed` | `true` | accept a self-signed certificate from the upper hub |

Make the credentials on the upper hub with `hivemind-core add-client`.

---
[← Clients](clients.md) · [Home](index.md) · [Security model →](security.md)
