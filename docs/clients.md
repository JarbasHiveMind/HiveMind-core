# Add and manage clients
<!-- agent-hint
covers: the hivemind-core CLI commands that add, list, change and remove clients
source: hivemind_core/scripts.py, hivemind_core/database.py
generated: no
verify: for c in $(grep -o '^\$ hivemind-core [a-z-]*' docs/clients.md | awk '{print $3}' | sort -u); do hivemind-core $c --help >/dev/null 2>&1 || exit 1; done
see: configuration.md
-->

A client is one row in the hub database. A satellite, a bridge or a lower hub uses the access key and the password of its row to connect. This page shows how to add a client, grant it message types, list the clients and reset a client after it changes its key.

## Example

```text
$ hivemind-core add-client --name kitchen --password correct-horse-battery-staple-91 --access-key 0123456789abcdef0123456789abcdef --allow ovos.utterance.handle --allow recognizer_loop:utterance
Database backend: SQLiteDB
Credentials added to database!

Node ID: 1
Admin Privileges: False
Friendly Name: kitchen
Access Key: 0123456789abcdef0123456789abcdef
Password: correct-horse-battery-staple-91
Allowed Message Types: ovos.utterance.handle, recognizer_loop:utterance
```

The commands also write log lines to the terminal. The examples on this page omit them.

## Steps

### Add a client

1. Run `add-client`. Without `--access-key` and `--password`, the hub makes random values:

   ```text
   $ hivemind-core add-client --name living-room
   Database backend: SQLiteDB
   Credentials added to database!

   Node ID: 2
   Admin Privileges: False
   Friendly Name: living-room
   Access Key: 8af90631d5f749b60adaf00370585d6f
   Password: b51a87e4d998a59a7382625b1cb20bd4
   Allowed Message Types: (none — the client is DENIED on every message)

   NOTE: Allowed message types is empty — this client will be DENIED on every message.
         Grant access explicitly, e.g.:
         hivemind-core allow-msg ovos.utterance.handle recognizer_loop:utterance 2
         (a client is admitted on the exact topic it sends: ovos.utterance.handle is
         the current name, recognizer_loop:utterance the legacy one)
         (admin status does not exempt a client from the message type whitelist)
   ```

2. Give the access key and the password to the satellite.

3. Grant the message types that the client sends. A client with no types gets a `hive.policy.denied` reply to each message. [Policies and ACLs](policies.md) explains the whitelist.

   ```text
   $ hivemind-core allow-msg speak 1
   Allowed 'speak' for kitchen
   ```

   With two or more arguments, the last argument is the client. `allow-msg ovos.utterance.handle speak 1` grants two types to client 1.

The hub refuses a password that is easy to guess:

```text
$ hivemind-core add-client --name weak --password abc
Usage: hivemind-core add-client [OPTIONS]
Try 'hivemind-core add-client --help' for help.

Error: Invalid value for --password: password is too guessable (~4 bits of resistance; 40 required). Sequences like "abc" or "6543" are easy to guess. Use a longer passphrase, or NoiseHandShake with a high-entropy secret. Pass min_bits=0 to bypass this check (not recommended).
Pass --allow-weak-password to override.
```

The limit is `min_password_bits` in `server.json`.

### List the clients

```text
$ hivemind-core list-clients
                             HiveMind Credentials:
┏━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ ID ┃    Name     ┃         Access Key          ┃          Password           ┃
┡━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1  │   kitchen   │ 0123456789abcdef0123456789… │ correct-horse-battery-stap… │
│ 2  │ living-room │ 8af90631d5f749b60adaf00370… │ b51a87e4d998a59a7382625b1c… │
└────┴─────────────┴─────────────────────────────┴─────────────────────────────┘
```

The table cuts long values to the terminal width. `export-clients --path clients.csv` writes the full values to a CSV file.

### Change permissions

```text
$ hivemind-core blacklist-escalate 1
Blacklisted 'ESCALATE' messages for kitchen
$ hivemind-core make-admin 2
Gave administrator powers to living-room
$ hivemind-core blacklist-intent weather.intent 1
Blacklisted 'weather.intent' for kitchen
```

The hub reads the permissions of a connected client from the database again, at most 5 seconds after a change. The client does not need to reconnect.

### Reset the Noise pin

The hub records the Noise static key of a client on its first handshake (the pin). When a client is reinstalled or moves to other hardware, its key changes, and the hub refuses it. The hub log names the command to run. After you make sure that the change is real, clear the pin:

```text
$ hivemind-core reset-noise-pin 1
Forgot the pinned Noise key for kitchen. Its next connection will pin the key it presents.
```

When no pin is recorded, the command prints `kitchen has no pinned Noise key — nothing to reset`. [Security model](security.md) explains the pin.

### Remove a client

```text
$ hivemind-core delete-client 1 --yes
Revoked credentials!

Node ID: 1
Friendly Name: kitchen
Access Key: 0123456789abcdef0123456789abcdef
Password: correct-horse-battery-staple-91
```

Without `--yes`, the command asks for confirmation.

## Reference

Each command that takes `NODE_ID` also accepts the access key. Without `NODE_ID`, the command asks for the client. Run `hivemind-core <command> --help` for the options of a command.

| Command | Effect |
| :--- | :--- |
| `add-client` | add a client; options `--name`, `--access-key`, `--password`, `--admin`, `--metadata`, `--allow`, `--allow-weak-password` |
| `list-clients` | print a table of the clients |
| `export-clients --path FILE` | write the clients with their full credentials to a CSV file |
| `rename-client NODE_ID --name NAME` | change the name of a client |
| `delete-client NODE_ID [--yes]` | remove a client |
| `allow-msg TYPE... NODE_ID` | add message types to the whitelist |
| `blacklist-msg TYPE NODE_ID` | remove a message type from the whitelist |
| `allow-broadcast`, `blacklist-broadcast` | set the BROADCAST permission |
| `allow-propagate`, `blacklist-propagate` | set the PROPAGATE and CASCADE permission |
| `allow-escalate`, `blacklist-escalate` | set the ESCALATE and QUERY permission |
| `make-admin`, `revoke-admin` | set the admin flag |
| `blacklist-skill`, `allow-skill` | edit `skill_blacklist` in the client metadata |
| `blacklist-intent`, `allow-intent` | edit `intent_blacklist` in the client metadata |
| `set-metadata NODE_ID` | set client metadata: `--metadata JSON`, `--key K --value V`, or `--unset K` |
| `reset-noise-pin NODE_ID` | forget the pinned Noise static key of a client |
| `derive-psk --password P --node-id ID` | print the Noise pre-shared key for a device that cannot run argon2id |
| `migrate-db --from MODULE --to MODULE` | copy all clients to another database backend; the source stays as it is |
| `policy list`, `policy test KEY TYPE` | show the policy chain, or test one message type for one client |
| `print-config` | print the configuration |
| `listen` | start the hub |

A client row starts with these values:

| Field | Start value |
| :--- | :--- |
| `allowed_types` | empty, or the `--allow` values |
| `is_admin` | `False` |
| `can_broadcast` | `True` (BROADCAST also needs `is_admin`) |
| `can_propagate` | `True` |
| `can_escalate` | `True` |

---
[← Install and run](install-and-run.md) · [Home](index.md) · [Configuration →](configuration.md)
