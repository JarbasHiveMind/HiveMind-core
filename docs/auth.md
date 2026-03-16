# Authentication and Client Management

Client management is handled through the `hivemind-core` CLI and the `hivemind_core.database.HiveMindDatabase` interface.

## Adding a Client

To add a new satellite, use the `add-client` command (implemented in `hivemind_core.scripts.add_client`):

```bash
hivemind-core add-client --name "LivingRoom-Sat"
```

This generates:
- **Node ID**: Unique integer ID.
- **Access Key**: Public identifier for the client.
- **Password**: Secret used for the handshake.

## Managing Permissions

Permissions are managed by the `HiveMindDatabase` and its associated methods.

### Blacklisting Skills
To prevent a specific client (ID 1) from using a specific skill:
```bash
hivemind-core blacklist-skill "mycroft-weather.mycroftai" 1
```
- **Source**: `hivemind_core.database.HiveMindDatabase.blacklist_skill`

### Allowing Messages
By default, most message types are restricted. To allow a client to receive `speak` messages:
```bash
hivemind-core allow-msg "speak" 1
```
- **Source**: `hivemind_core.database.HiveMindDatabase.allow_msg`

## Database Backends
HiveMind supports multiple database plugins for storing client credentials:
- **JSON**: `hivemind_core.database.JsonDB` (implemented via `json_database.hpm.JsonDB`).
- **SQLite**: `hivemind_core.database.SQLiteDB` (implemented via `hivemind_sqlite_database.SQLiteDB`).
- **Redis**: `hivemind_core.database.RedisDB` (implemented via `hivemind_redis_database.RedisDB`).
