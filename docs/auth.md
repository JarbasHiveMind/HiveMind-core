# Authentication and Client Management

Client management runs through the `hivemind-core` CLI and the `hivemind_core.database.ClientDatabase` interface.

## Adding a Client

To add a new satellite, use the `add-client` command (implemented in `hivemind_core.scripts.add_client`):

```bash
hivemind-core add-client --name "LivingRoom-Sat"
```

This generates:
- **Node ID**: a unique integer ID.
- **Access Key**: a public identifier for the client.
- **Password**: a secret used for the handshake.

## Managing Permissions

The CLI writes permissions to the client row through `ClientDatabase`.

### Blacklisting Skills

To stop a specific client (ID 1) from using a specific skill:

```bash
hivemind-core blacklist-skill "mycroft-weather.mycroftai" 1
```

- **Source**: `hivemind_core.scripts.blacklist_skill`

### Allowing Messages

New clients start with an empty `allowed_types` whitelist. The server denies every
message, and every binary payload, that such a client sends. To let a client send `speak`
messages:

```bash
hivemind-core allow-msg "speak" 1
```

- **Source**: `hivemind_core.scripts.allow_msg`

## Database Backends

HiveMind supports multiple database plugins for storing client credentials:

- **SQLite** (default for fresh installs): `hivemind_sqlite_database.SQLiteDB`.
- **JSON** (kept for existing JSON deployments): `json_database.hpm.JsonDB`.
- **Redis**: `hivemind_redis_database.RedisDB`.

---
[Home](index.md) · [Installation →](installation.md)
