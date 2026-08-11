# CLI Reference

All administration is done through the `hivemind-core` command. If you omit the numeric
client ID from any command that requires one, you will be prompted to select interactively.

```
Usage: hivemind-core [OPTIONS] COMMAND [ARGS]...

Commands:
  listen              Start the HiveMind Core server
  add-client          Register credentials for a new satellite
  list-clients        Print all registered clients
  rename-client       Rename a registered client
  delete-client       Revoke a client's credentials
  make-admin          Grant administrator status to a client
  revoke-admin        Revoke administrator status from a client
  allow-msg           Add a message type to a client's allowed_types whitelist
  blacklist-msg       Remove a message type from a client's allowed_types whitelist
  allow-escalate      Allow ESCALATE messages from a client
  blacklist-escalate  Deny ESCALATE messages from a client
  allow-propagate     Allow PROPAGATE messages from a client
  blacklist-propagate Deny PROPAGATE messages from a client
  allow-broadcast     Allow BROADCAST messages from a client
  blacklist-broadcast Deny BROADCAST messages from a client
  blacklist-skill     Add a skill to OVOSAgentPolicy's skill_blacklist (via metadata)
  allow-skill         Remove a skill from OVOSAgentPolicy's skill_blacklist (via metadata)
  blacklist-intent    Add an intent to OVOSAgentPolicy's intent_blacklist (via metadata)
  allow-intent        Remove an intent from OVOSAgentPolicy's intent_blacklist (via metadata)
  set-metadata        Set arbitrary Client.metadata keys
  migrate-db          Copy all clients from one database backend to another
  export-clients      Export clients and credentials to a CSV file
  derive-psk          Derive a pre-shared key from a site password and node id
  print-config        Print the server configuration as JSON
  policy list         Print the loaded policy chain
  policy test         Dry-run a message through the policy chain
```

---

## `listen`

Start the HiveMind Core server.

```bash
hivemind-core listen
```

Reads plugin configuration from `~/.config/hivemind-core/server.json`. All network
protocol plugins start concurrently.

---

## `add-client`

Register a new satellite.

```bash
hivemind-core add-client
hivemind-core add-client --name "kitchen-pi"
hivemind-core add-client --name "api-bot" --access-key "mykey" --password "mypass"
hivemind-core add-client --name "api-bot" --metadata '{"tier":"pro"}'
```

Options:

| Flag | Default | Purpose |
|---|---|---|
| `--name TEXT` | auto-generated | Human-readable client name |
| `--access-key TEXT` | random | API key the satellite presents on connect |
| `--password TEXT` | random | Used for key derivation |
| `--crypto-key TEXT` | random | Legacy encryption key (deprecated; only for old clients without password support) |
| `--admin BOOL` | `False` | Mark the client as an administrator. Informational: it grants no admission bypass |
| `--metadata JSON` | `{}` | Initial `Client.metadata` as a JSON object |
| `--allow-weak-password` | off | Accept a password below `min_password_bits` |

The database backend comes from `server.json`. There is no per-command override flag.

A freshly created client has an **empty** `allowed_types` whitelist. It is denied all
messages until you run `allow-msg`.

---

## `list-clients`

Print all registered clients and their credentials.

```bash
hivemind-core list-clients
```

---

## `rename-client`

```bash
hivemind-core rename-client 1 --name "new name"
```

---

## `delete-client`

Revoke a client's credentials. The row is deleted from the database.

```bash
hivemind-core delete-client 1
```

---

## `make-admin` / `revoke-admin`

Set `Client.is_admin`. This is **informational only**. It does not bypass the policy
chain or the `allowed_types` whitelist.

```bash
hivemind-core make-admin 1
hivemind-core revoke-admin 1
```

---

## `allow-msg` / `blacklist-msg`

Manage the `allowed_types` whitelist for a client. The whitelist is the primary ACL
enforced by `MessageTypeACLPolicy` (always first in the policy chain). An empty whitelist
denies all messages.

```bash
# Grant a message type
hivemind-core allow-msg "recognizer_loop:utterance" 1
hivemind-core allow-msg "speak" 1

# Revoke a message type
hivemind-core blacklist-msg "speak" 1
```

Binary payloads cross the same gate. A client with an empty whitelist cannot send audio,
images, or files either.

Changes take effect on the **next** message from that client. No reconnect is needed.

---

## `allow-escalate` / `blacklist-escalate`

Control whether a client may send `ESCALATE` HiveMessages.

```bash
hivemind-core allow-escalate 1
hivemind-core blacklist-escalate 1
```

---

## `allow-propagate` / `blacklist-propagate`

Control whether a client may send `PROPAGATE` HiveMessages.

```bash
hivemind-core allow-propagate 1
hivemind-core blacklist-propagate 1
```

---

## `allow-broadcast` / `blacklist-broadcast`

Control whether a client may send `BROADCAST` HiveMessages.

> The client must also be admin. BROADCAST is gated on `is_admin` **and**
> `can_broadcast`, so granting this to a non-admin changes nothing — the CLI
> prints a note saying so.

```bash
hivemind-core allow-broadcast 1
hivemind-core blacklist-broadcast 1
```

---

## `blacklist-skill` / `allow-skill` / `blacklist-intent` / `allow-intent`

These commands manage OVOS-specific blacklists stored in `Client.metadata`.
`OVOSAgentPolicy` (in `hivemind-ovos-agent-plugin`) reads `metadata["skill_blacklist"]`
and `metadata["intent_blacklist"]` and injects them into the OVOS session for each
message from that client. These commands have **no effect** unless `OVOSAgentPolicy` is
configured in `policy.chain`.

```bash
hivemind-core blacklist-skill "skill-weather" 1
hivemind-core allow-skill "skill-weather" 1
hivemind-core blacklist-intent "skill-weather.WeatherIntent" 1
hivemind-core allow-intent "skill-weather.WeatherIntent" 1
```

---

## `set-metadata`

Write arbitrary key/value pairs to `Client.metadata`. Policy plugins consume metadata.
Each plugin reads the keys it knows about.

```bash
# Merge a JSON object
hivemind-core set-metadata 1 --metadata '{"tier":"pro","region":"eu"}'

# Set a single key
hivemind-core set-metadata 1 --key tier --value pro

# Set a JSON-typed value
hivemind-core set-metadata 1 --key skill_blacklist --value '["skill-weather"]'

# Remove a key
hivemind-core set-metadata 1 --unset region
```

---

## `migrate-db`

Migrate the client database between backends. Both `--from` and `--to` accept a backend
plugin name.

Both flags take a database plugin entry-point name. `--from` defaults to
`hivemind-json-db-plugin` and `--to` defaults to `hivemind-sqlite-db-plugin`.

```bash
# Migrate from JSON to SQLite (both defaults, so the flags are optional)
hivemind-core migrate-db --from hivemind-json-db-plugin --to hivemind-sqlite-db-plugin

# Migrate from SQLite to Redis
hivemind-core migrate-db --from hivemind-sqlite-db-plugin --to hivemind-redis-db-plugin
```

The command reads the target backend's connection settings from `server.json`. It takes
no host, port, or password flags. The source database is left untouched.

---

## `export-clients`

Write every client record to a CSV file. The columns are `client_id`, `name`, `is_admin`,
`access_key`, `password`, and `crypto_key`.

```bash
hivemind-core export-clients --path /srv/backup/
```

`--path` accepts a file or a directory. If it names a directory, the command writes
`hivemind_clients.csv` inside it. If you omit `--path`, the CSV goes to stdout.

The file holds plaintext credentials. Store it accordingly.

---

## `derive-psk`

Print the pre-shared key that a site password and a node id produce. Use it to configure
a client that authenticates with a shared site password.

```bash
hivemind-core derive-psk --password "site-secret" --node-id "kitchen-pi"
```

Both flags are mandatory.

---

## `print-config`

Print the active server configuration as JSON.

```bash
hivemind-core print-config
```

---

## `policy list` / `policy test`

Inspect the admission chain. `policy list` prints the built-in policies first, then the
plugins built from `policy.chain`.

```bash
hivemind-core policy list
```

`policy test` builds a fake message of the given type, runs the full chain against the
client that owns the given access key, and prints the verdict as JSON.

```bash
hivemind-core policy test 42caf3d2405075fb9e7a4e1ff44e4c4f "speak"
```

Source: `hivemind_core/scripts.py`

---
[← Configuration](configuration.md) · [Home](README.md) · [Policy Chain →](policy.md)
