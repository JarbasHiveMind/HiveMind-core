[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/JarbasHiveMind/HiveMind-core)

# HiveMind Core

HiveMind is a [protocol](https://jarbashivemind.github.io/HiveMind-community-docs/04_protocol/) for communication and collaboration between devices and AI agents in one network.
It lets lightweight devices, called **satellites**, connect to a central HiveMind Core server, with customizable permissions and centralized control.

HiveMind also supports [connections between HiveMind Core servers](https://jarbashivemind.github.io/HiveMind-community-docs/15_nested/), so you can build layered, scalable environments.

HiveMind started as part of the [OpenVoiceOS (OVOS)](https://github.com/OpenVoiceOS/) ecosystem. You can adapt it to other AI backend systems.

For more details and demonstrations, check the [YouTube channel](https://www.youtube.com/channel/UCYoV5kxp2zrH6pnoqVZpKSA/).

---

- [HiveMind Core](#hivemind-core)
   * [Key Features](#key-features)
   * [Modular Design with Plugins](#modular-design-with-plugins)
   * [Protocol Configuration](#protocol-configuration)
   * [Quick Start](#quick-start)
      + [Installation](#installation)
      + [Adding a Satellite](#adding-a-satellite)
      + [Granting Message Types](#granting-message-types)
      + [Running the Server](#running-the-server)
   * [Commands Overview](#commands-overview)
   * [Plugins Overview](#plugins-overview)
   * [Clients Overview](#clients-overview)
   * [Next Steps](#next-steps)
   * [License](#license)
   * [Trademark](#trademark)
   * [Contributing](#contributing)

---

## Key Features

- **Modular design**: extend functionality with plugins for different protocols and behaviors.
- **Protocol flexibility**: use HiveMind with different **network**, **agent**, and **binary protocols**.
- **Customizable database options**: JSON, SQLite, and Redis.
- **Centralized control**: manage and monitor devices from one HiveMind Core server.
- **[Fine-grained permissions](https://jarbashivemind.github.io/HiveMind-community-docs/16_permissions/)**: control
  access to skills, intents, and message types for each satellite.
- **Multi-agent support**: integrate AI assistants such as [OpenVoiceOS](https://github.com/OpenVoiceOS/)
  or [LLMs](https://github.com/OpenVoiceOS/ovos-persona).

---

## Modular Design with Plugins

HiveMind is modular. You customize its behavior through plugins managed by the **HiveMind Plugin Manager**.

- **Transport mechanism**: the protocol does not specify **how** messages are transported. **Network protocol plugins** implement this (for example, Websockets, HTTP).
- **Payload handling**: the protocol does not dictate **who** handles the messages. **Agent protocol plugins** implement this (for example, OVOS, Persona).
- **Message format**: the protocol supports **JSON data** modeled after the `Message` [structure from OVOS](https://jarbashivemind.github.io/HiveMind-community-docs/13_mycroft/), and **binary** data. **Binary data protocol plugins** implement what happens to received binary data (for example, processing incoming audio).
- **Database**: **database plugins** implement how client credentials are stored (for example, JSON, SQLite, Redis).

---

## Protocol Configuration

HiveMind Core supports a configuration file. This lets you define server settings without long command-line arguments.

> The configuration file is stored at `~/.config/hivemind-core/server.json`

The default configuration:

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
  "policy": {
    "chain": [
      {"module": "hivemind-ovos-agent-policy"}
    ]
  },
  "database": {
    "module": "hivemind-sqlite-db-plugin",
    "hivemind-sqlite-db-plugin": {
      "name": "clients",
      "subfolder": "hivemind-core"
    }
  }
}
```

> **Default backend:** fresh installs use **SQLite** (transactional, concurrency-safe, stdlib). An existing JSON deployment (a `clients.json` already on disk) keeps using JSON, so upgrades never strand the credentials store. Move an existing store with `hivemind-core migrate-db --from hivemind-json-db-plugin --to hivemind-sqlite-db-plugin`. Both flags take a database plugin entry-point name, so the same command moves a store between JSON, SQLite, and Redis.

### Policy Admission Chain

Every inbound message passes through an ordered **policy admission chain** before it reaches the agent bus. See [issue #85](https://github.com/JarbasHiveMind/HiveMind-core/issues/85) for the full spec.

**How it works:**

1. `MessageTypeACLPolicy` is **always prepended** to the chain. Configuration cannot remove it. It enforces the per-client `allowed_types` whitelist: if `message.msg_type` is not in the client's `allowed_types`, the message is denied. Binary payloads cross the same gate, so an empty whitelist denies binary too. A failed database lookup denies with `policy_error`. `Client.is_admin` is informational and gives no admission bypass. Admins follow the whitelist like any other client (`MessageTypeACLPolicy` in `hivemind_core/policy.py`).
2. `DefaultSessionPolicy` is **always prepended** too, right after it. Configuration cannot remove it. It denies any non-admin client that puts the reserved `default` session id in `message.context["session"]`: that id addresses the host's own device-local session, so a peer must not write into it.
3. Configured plugins in `policy.chain` run after the built-ins, in order. Each plugin can deny the message or contribute mutations applied before the next plugin runs.
4. The chain is **fail-closed by default**. An unhandled exception in a policy becomes `Verdict.deny("policy_error", ...)` (`PolicyChain.review` in `hivemind_core/policy.py`). Mark a single chain entry with `"optional": true` to make the chain log a warning and continue instead. The two built-in policies ignore that flag and stay mandatory.
5. If the chain fails to build at startup, HiveMind installs a `DenyAllPolicy` fallback, which rejects every message with `code="policy_chain_unavailable"` until you fix the configuration (`DenyAllPolicy` in `hivemind_core/policy.py`).

**Denied messages** get a `hive.policy.denied` BUS response with this payload:

```json
{
  "denied_type": "<msg_type or 'binary'>",
  "code": "<verdict code>",
  "reason": "<human-readable reason>",
  "data": {}
}
```

`handle_inject_agent_msg` runs `policy_chain.review()` then `policy_chain.observe()` for every accepted message. `handle_binary_message` runs `policy_chain.review_binary()` (both in `hivemind_core/protocol.py`).

**ACL model: whitelist-only, deny-by-default**

- `allowed_types` is the only ACL field on `HiveMindClientConnection`. There is no message blacklist (`HiveMindClientConnection` in `hivemind_core/protocol.py`).
- A freshly created client (via `add-client`) has an **empty** `allowed_types` list. HiveMind denies it all messages until the operator explicitly grants types with `allow-msg`. This applies to admin clients too. `Client.is_admin` is informational only and gives no admission bypass.

To grant a message type:

```bash
$ hivemind-core allow-msg "recognizer_loop:utterance" 1
$ hivemind-core allow-msg "speak" 1
```

**Removing a type** (mutates `allowed_types`, not deprecated):

```bash
$ hivemind-core blacklist-msg "speak" 1
```

**Skill and intent filtering** are OVOS-specific concerns handled by `OVOSAgentPolicy` (shipped with `hivemind-ovos-agent-plugin`, the default `agent_protocol`). The CLI commands `blacklist-skill`, `allow-skill`, `blacklist-intent`, and `allow-intent` manage the `skill_blacklist` / `intent_blacklist` lists in `Client.metadata`, which `OVOSAgentPolicy` injects into the OVOS session. They take effect only when you configure that policy in `policy.chain`. For any other policy-relevant key, use **`set-metadata`** to write arbitrary `Client.metadata` (`hivemind_core/scripts.py`).

**On-disk migration of legacy blacklist fields.** Database backends (for example, `hivemind-sqlite-database`, `hivemind-redis-database`) implement the `AbstractDB.migrate(from_version)` hook from `hivemind-plugin-manager` and run a one-shot `v1 → v2` migration on first open. The migration folds any legacy top-level `intent_blacklist` / `skill_blacklist` / `message_blacklist` storage (SQLite columns, JSON keys, Redis hash fields) into each row's `metadata` dict via `setdefault` (explicit metadata wins), then clears the legacy storage. Backends track their schema version natively (SQLite `PRAGMA user_version`, Redis sentinel key), so the migration runs exactly once per database. Third-party backends that do not override `migrate()` keep working. The property shims on `Client` keep read-path code agnostic to on-disk shape.

To add more policies, extend the `policy.chain` list with plugin module names:

```json
"policy": {
  "chain": [
    {"module": "hivemind-ovos-agent-policy"},
    {"module": "hivemind-intent-quota-policy", "config": {"limit": 100}}
  ]
}
```

Drop `hivemind-ovos-agent-policy` from the list only if you run a non-OVOS agent backend.

---

## Quick Start

HiveMind Core provides a command-line interface (CLI) for managing clients, permissions, and connections.

### Installation

```bash
pip install hivemind-core
```

### Adding a Satellite

Add credentials for each satellite device:

```bash
$ hivemind-core add-client --name "HiveMind-Node-2"
Database backend: SQLiteDB
Credentials added to database!

Node ID: 3
Friendly Name: HiveMind-Node-2
Access Key: 42caf3d2405075fb9e7a4e1ff44e4c4f
Password: 5ae486f7f1c26bd4645bd052e4af3ea3
```

**NOTE**: You must provide this information on the client devices so they can connect.

### Granting Message Types

A new client starts with an **empty** `allowed_types` whitelist. The server denies every
message, and every binary payload, from that client until you grant the types it needs:

```bash
$ hivemind-core allow-msg "recognizer_loop:utterance" 3
$ hivemind-core allow-msg "speak" 3
```

If you skip this step, the client connects and then gets a `hive.policy.denied` answer to
each message.

### Running the Server

Start the HiveMind Core server to accept connections:

```bash
$ hivemind-core listen
```

---

## Commands Overview

The HiveMind Core CLI supports these commands:

```bash
$ hivemind-core --help
Usage: hivemind-core [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  add-client           add credentials for a client
  allow-msg            allow a message type to be sent from a client
  blacklist-msg        remove a message type from a client's allowed list
  allow-escalate       allow ESCALATE messages from a client
  blacklist-escalate   deny ESCALATE messages from a client
  allow-propagate      allow PROPAGATE messages from a client
  blacklist-propagate  deny PROPAGATE messages from a client
  allow-broadcast      allow BROADCAST messages from a client
  blacklist-broadcast  deny BROADCAST messages from a client
  delete-client        remove credentials for a client
  list-clients         list clients and credentials
  listen               start listening for HiveMind connections
  make-admin           grant administrator privileges to a client
  revoke-admin         revoke administrator privileges from a client
  rename-client        rename a client in the database
  allow-intent         remove an intent from a client's blacklist (OVOS-policy)
  allow-skill          remove a skill from a client's blacklist (OVOS-policy)
  blacklist-intent     blacklist an intent for a client (OVOS-policy)
  blacklist-skill      blacklist a skill for a client (OVOS-policy)
  set-metadata         set arbitrary metadata on a client (read by policy plugins)
  derive-psk           derive a pre-shared key from a site password and node id
  export-clients       export clients and credentials to a CSV file
  migrate-db           copy all clients from one database backend to another
  policy               inspect the policy admission chain
  print-config         print the server configuration
```

For detailed help on each command, use `--help` (for example, `hivemind-core add-client --help`).

> **Tip**: if you do not specify the numeric client_id in your commands, HiveMind prompts you for it.

<details>
  <summary>Click for more details</summary>

---

### `add-client`

Add credentials for a new client that will connect to the HiveMind instance.

```bash
$ hivemind-core add-client --name "satellite_1" --access-key "mykey123" --password "mypass"
```

- **When to use**:
  Use this command when you set up a new HiveMind client (for example, a Raspberry Pi or another IoT device). It provides credentials for secure communication with the server.
- **Optional metadata**:
  Admins can attach plugin-specific client context with `--metadata`:

```bash
hivemind-core add-client --name "satellite_1" --metadata '{"account_id":"acct_123","device_type":"satellite"}'
```

---

### `list-clients`

List all registered clients and their credentials.

```bash
$ hivemind-core list-clients
```

- **When to use**:
  Use this command to view or inspect all registered clients. It helps with debugging or managing devices connected to HiveMind.

---

### `rename-client`

Rename a registered client.

```bash
$ hivemind-core rename-client 1 --name "new name"
```

- **When to use**:
  Use this command when you need to change the name of an existing client in the database.

---

### `delete-client`

Remove a registered client from the HiveMind instance.

```bash
$ hivemind-core delete-client 1
```

- **When to use**:
  Use this command to revoke a client's access, for example when a device is lost, no longer in use, or compromised.

---

### `allow-msg`

Grant a specific message type to a client's `allowed_types` whitelist. New clients have an **empty** whitelist and are denied all messages until you grant at least one type.

```bash
$ hivemind-core allow-msg "recognizer_loop:utterance" 1
$ hivemind-core allow-msg "speak" 1
```

- **When to use**:
  Use this command after `add-client` to grant the message types the client needs. Without any `allow-msg` calls, the client is locked out (deny-by-default).

---

### `blacklist-msg`

Revoke specific message types from being allowed to be sent by a client.

```bash
$ hivemind-core blacklist-msg "speak"
```

- **When to use**:
  Use this command to stop specific message types from being sent by a client. It adds a layer of control over communication.

---

### `blacklist-skill` / `allow-skill` / `blacklist-intent` / `allow-intent` (OVOS-policy)

> Skill and intent filtering is an OVOS-specific concern handled by `OVOSAgentPolicy` (shipped with `hivemind-ovos-agent-plugin`). These commands manage the `skill_blacklist` / `intent_blacklist` lists in `Client.metadata`. `OVOSAgentPolicy` injects them into the OVOS session. They take effect only when you configure that policy in `policy.chain` (`hivemind_core/scripts.py`).

```bash
$ hivemind-core blacklist-skill "skill-weather" 1   # writes Client.metadata["skill_blacklist"]
$ hivemind-core allow-skill "skill-weather" 1
$ hivemind-core blacklist-intent "intent.check_weather" 1  # writes Client.metadata["intent_blacklist"]
$ hivemind-core allow-intent "intent.check_weather" 1
```

---

### `set-metadata`

Set arbitrary `Client.metadata` on an existing client. Policy plugins consume metadata keys. `OVOSAgentPolicy` reads `skill_blacklist` / `intent_blacklist`. Other policies read their own keys. Merge a JSON object, set a single entry, or remove a key:

```bash
$ hivemind-core set-metadata 1 --metadata '{"tier":"pro","region":"eu"}'   # merge
$ hivemind-core set-metadata 1 --key skill_blacklist --value '["skill-weather"]'
$ hivemind-core set-metadata 1 --key tier --value pro    # non-JSON value kept as a string
$ hivemind-core set-metadata 1 --unset region            # remove a key
```

---

### `listen`

Start the HiveMind instance to listen for client connections.

```bash
$ hivemind-core listen
```

- **When to use**:
  Use this command to start the HiveMind instance so it accepts connections from clients (for example, satellite devices). Configure the host, port, and security options as needed.

---

</details>


---

## Plugins Overview

| **Category**         | **Plugin**                                                                                   | **Description**                                                                                                                                                                                          |
|----------------------|----------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Network Protocol** | [hivemind-websocket-protocol](https://github.com/JarbasHiveMind/hivemind-websocket-protocol) | Provides WebSocket-based communication for HiveMind, for real-time data exchange.                                                                                                                   |
|   | [hivemind-http-protocol](https://github.com/JarbasHiveMind/hivemind-http-protocol) | Provides HTTP-based communication for HiveMind, for cases where a persistent connection is undesirable or not possible.                                                                                                                   |
| **Binary Protocol**  | [hivemind-audio-binary-protocol](https://github.com/JarbasHiveMind/hivemind-audio-binary-protocol)                     | Listens for incoming audio and processes it with the [ovos-plugin-manager](https://github.com/OpenVoiceOS/ovos-plugin-manager), connecting HiveMind to audio input systems. |
| **Agent Protocol**   | [OpenVoiceOS](https://github.com/OpenVoiceOS/ovos-core)                                      | Integration with OpenVoiceOS, through [ovos-bus-client](https://github.com/OpenVoiceOS/ovos-bus-client/blob/dev/ovos_bus_client/hpm.py), for communication with OVOS systems.                                       |
|                      | [Persona](https://github.com/OpenVoiceOS/ovos-persona)                                | LLM (Large Language Model) integration provided by [ovos-persona](https://github.com/OpenVoiceOS/ovos-persona/blob/dev/ovos_persona/hpm.py), which works with all OpenAI server compatible projects.                                         |
| **Database**         | [hivemind-sqlite-database](https://github.com/JarbasHiveMind/hivemind-sqlite-database)       | SQLite-based database plugin for managing local data in HiveMind.                                                                                                                     |
|                      | [hivemind-redis-database](https://github.com/JarbasHiveMind/hivemind-redis-database)         | Redis integration for scalable, in-memory database storage with fast data access.                                                                                                                      |
|                      | [hivemind-json-database](https://github.com/TigreGotico/json_database/pull/7)                | A JSON-based database plugin provided by [json-database](https://github.com/TigreGotico/json_database), for lightweight storage and retrieval using the JSON format.                                    |

---

## Clients Overview

| **Category**   | **Client**                                                                      | **Description**                                                                                              |
|----------------|-----------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|
| **Satellites** | [Voice Satellite](https://github.com/OpenJarbas/HiveMind-voice-sat)             | Standalone OVOS *local* audio stack for HiveMind.                                                            |
|                | [Voice Relay](https://github.com/JarbasHiveMind/HiveMind-voice-relay)           | Lightweight audio satellite. STT/TTS runs *server* side. **Requires** `hivemind-audio-binary-protocol`.              |
|                | [Mic Satellite](https://github.com/JarbasHiveMind/hivemind-mic-satellite)       | Only VAD runs on the device. Audio streams to the server and processes fully *server* side. **Requires** `hivemind-audio-binary-protocol`. |
|                | [Web Chat](https://github.com/OpenJarbas/HiveMind-webchat)                      | *Client-side* browser HiveMind connection for web-based communication.                                       |
| **Bridges**    | [Mattermost Bridge](https://github.com/OpenJarbas/HiveMind_mattermost_bridge)   | Bridge for talking to HiveMind through Mattermost.                                                                |
|                | [Matrix Bridge](https://github.com/JarbasHiveMind/HiveMind-matrix-bridge)       | Bridge for talking to HiveMind through Matrix.                                                                    |
|                | [DeltaChat Bridge](https://github.com/JarbasHiveMind/HiveMind-deltachat-bridge) | Bridge for talking to HiveMind through DeltaChat.                                                                |

---

## Next Steps

- Visit the [documentation](https://jarbashivemind.github.io/HiveMind-community-docs) for detailed guides.
- Join the [HiveMind Matrix Chat](https://matrix.to/#/#jarbashivemind:matrix.org) for support and updates.
- Explore other plugins and expand your HiveMind setup.

---

## License

HiveMind-core is licensed under the **[Apache License 2.0](./LICENSE)**, matching the rest of the HiveMind ecosystem.

> Releases up to **`hivemind-core` 3.4.0** were Apache-2.0. The **4.x** series shipped under AGPL-3.0 as a short-lived experiment. From this release forward, HiveMind-core returns to Apache-2.0. Previously published 3.x and 4.x releases on PyPI stay under the license they were published with.

### Trademark

The names **HiveMind**, **HiveMind-core**, **HiveMind Protocol**, the HiveMind logos, and any "HiveMind Compatible / Powered by HiveMind" marks are protected trademarks and are **not** licensed under Apache-2.0 (see Apache-2.0 §6). See [TRADEMARK-USAGE.md](./TRADEMARK-USAGE.md) for the brand-use policy. A no-cost trademark grant is available for nonprofits, academic projects, and OSI-licensed downstream projects.

### Supporting the project

If your organization depends on HiveMind-core in production, consider sponsoring the project, contracting paid support or custom integrations, or commissioning proprietary skills. Contact: **[jarbasai@mailfence.com](mailto:jarbasai@mailfence.com)**.

---

## Contributing

HiveMind-core welcomes external contributions. Inbound code is licensed under Apache-2.0 by default (per Apache-2.0 §5, no separate CLA needed).

- **Bugs & features**: open an issue on GitHub.
- **Pull requests**: target the `dev` branch. Keep changes focused and follow the existing code style.
- **Discussion**: [Matrix chat](https://matrix.to/#/#jarbashivemind:matrix.org).
