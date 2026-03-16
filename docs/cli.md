# CLI Reference

All commands are available under the `hivemind-core` entry point.

```
hivemind-core [COMMAND] [OPTIONS]
```

If `node_id` is optional on a command and is not provided, you will be shown an interactive client selection table.

---

## Server

### `listen`

Start the HiveMind server and begin accepting client connections.

```bash
hivemind-core listen
```

The server reads its configuration from `~/.config/hivemind-core/server.json`. See [Configuration](configuration.md) for details.

---

### `print-config`

Print the current server configuration as JSON.

```bash
hivemind-core print-config
```

---

## Client management

### `add-client`

Register a new satellite or client. If credentials are not provided, they are generated automatically.

```bash
hivemind-core add-client [OPTIONS]
```

| Option | Type | Description |
|---|---|---|
| `--name` | `str` | Friendly name for the client |
| `--access-key` | `str` | API access key (auto-generated if omitted) |
| `--password` | `str` | Password used for session key derivation (auto-generated if omitted) |
| `--crypto-key` | `str` | **Deprecated.** Legacy 16-character encryption key. Use `--password` instead |
| `--admin` | `bool` | Grant administrator privileges (default: `False`) |

**Example — auto-generated credentials:**

```bash
$ hivemind-core add-client --name "living-room-pi"
Credentials added to database!

Node ID: 1
Friendly Name: living-room-pi
Access Key: 42caf3d2405075fb9e7a4e1ff44e4c4f
Password: 5ae486f7f1c26bd4645bd052e4af3ea3
Encryption Key: f46351c54f61a715
```

Provide the **Access Key** and **Password** to the client device.

---

### `list-clients`

Display a table of all registered clients and their credentials.

```bash
hivemind-core list-clients
```

---

### `export-clients`

Export all client credentials to a CSV file (or print to stdout).

```bash
hivemind-core export-clients [--path PATH]
```

| Option | Description |
|---|---|
| `--path` | Output file or directory. If a directory, saves as `hivemind_clients.csv` |

---

### `rename-client`

Rename a registered client.

```bash
hivemind-core rename-client [NODE_ID] [--name NAME]
```

---

### `delete-client`

Remove a client's credentials, revoking its access.

```bash
hivemind-core delete-client [NODE_ID]
```

---

## Administrator privileges

### `make-admin`

Grant administrator privileges to a client. Admins can send `BROADCAST` messages and use the `default` session.

```bash
hivemind-core make-admin [NODE_ID]
```

### `revoke-admin`

Revoke administrator privileges from a client.

```bash
hivemind-core revoke-admin [NODE_ID]
```

---

## Message type permissions

By default, clients may only send a restricted set of message types (e.g. `recognizer_loop:utterance`). Use these commands to expand or restrict that set.

### `allow-msg`

Allow a client to send an additional OVOS message type.

```bash
hivemind-core allow-msg MSG_TYPE [NODE_ID]
```

```bash
# Allow a client to inject TTS commands directly
hivemind-core allow-msg speak 1
```

### `blacklist-msg`

Remove a message type from a client's allowed list.

```bash
hivemind-core blacklist-msg MSG_TYPE [NODE_ID]
```

---

## Routing permissions

### `allow-escalate` / `blacklist-escalate`

Control whether a client may send `ESCALATE` messages (forwarded up the hub hierarchy).

```bash
hivemind-core allow-escalate [NODE_ID]
hivemind-core blacklist-escalate [NODE_ID]
```

### `allow-propagate` / `blacklist-propagate`

Control whether a client may send `PROPAGATE` messages (forwarded to all peers and upstream hubs).

```bash
hivemind-core allow-propagate [NODE_ID]
hivemind-core blacklist-propagate [NODE_ID]
```

---

## Skill & intent permissions

These permissions are enforced by injecting blacklists into the OVOS session associated with the client's requests.

### `blacklist-skill` / `allow-skill`

Prevent or re-enable a skill from being triggered by a specific client.

```bash
hivemind-core blacklist-skill SKILL_ID [NODE_ID]
hivemind-core allow-skill SKILL_ID [NODE_ID]
```

```bash
hivemind-core blacklist-skill skill-weather.openvoiceos 1
```

### `blacklist-intent` / `allow-intent`

Prevent or re-enable a specific intent from being triggered by a client.

```bash
hivemind-core blacklist-intent INTENT_ID [NODE_ID]
hivemind-core allow-intent INTENT_ID [NODE_ID]
```

```bash
hivemind-core blacklist-intent skill-weather.openvoiceos:WeatherIntent 1
```
