[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/JarbasHiveMind/HiveMind-core)

# HiveMind Core

HiveMind is a flexible [protocol](https://jarbashivemind.github.io/HiveMind-community-docs/04_protocol/) that facilitates communication and collaboration among devices and AI agents within a unified network. 
It enables lightweight devices, called **satellites**, to connect to a central hub, with customizable permissions and centralized control.

HiveMind also supports [hierarchical hub-to-hub connections](https://jarbashivemind.github.io/HiveMind-community-docs/15_nested/), creating powerful, scalable smart environments.

Initially developed as part of the [OpenVoiceOS (OVOS)](https://github.com/OpenVoiceOS/) ecosystem, HiveMind is adaptable to various AI backend systems.

For more details and demonstrations, check our [YouTube channel](https://www.youtube.com/channel/UCYoV5kxp2zrH6pnoqVZpKSA/).

---

- [HiveMind Core](#hivemind-core)
   * [Key Features](#-key-features)
   * [Modular Design with Plugins](#-modular-design-with-plugins)
   * [Protocol Configuration](#-protocol-configuration)
   * [Quick Start](#-quick-start)
      + [Installation](#installation)
      + [Adding a Satellite](#adding-a-satellite)
      + [Running the Server](#running-the-server)
   * [Commands Overview](#-commands-overview)
   * [Plugins Overview](#-plugins-overview)
   * [Clients Overview](#-clients-overview)
   * [Next Steps](#-next-steps)
   * [License](#-license)
      + [AGPL-3.0 (Open Source)](#agpl-30-open-source)
      + [Commercial License](#commercial-license)
      + [Trademark and Branding Restrictions](#trademark-and-branding-restrictions)
   * [Contribution Policy](#-contribution-policy)
  
---

## **⚠️ Commercial Notice**

HiveMind-core **v4.0+** is licensed under **AGPL-3.0**. 

Any commercial deployment, proprietary integration, or internal service that cannot comply with AGPL disclosure obligations **requires a commercial license**. 

If you are upgrading from an older version, be aware that continuing to use HiveMind-core in production may expose your organization to legal obligations under AGPL.

> 💡 The last **Apache-2.0** release was `hivemind-core` **3.4.0**

Contact **[jarbasai@mailfence.com](mailto:jarbasai@mailfence.com)** to secure a license.

---

## 🌟 Key Features

- **Modular Design**: Easily extend functionality with plugins for different protocols and behaviors.
- **Protocol Flexibility**: Use HiveMind with different **network**, **agent**, and **binary protocols**.
- **Customizable Database Options**: Support for JSON, SQLite, and Redis.
- **Centralized Control**: Manage and monitor devices from a single hub.
- **[Fine-Grained Permissions](https://jarbashivemind.github.io/HiveMind-community-docs/16_permissions/)**: Control
  access to skills, intents, and message types for each satellite.
- **Multi-Agent Support**: Integrate various AI assistants, such as [OpenVoiceOS](https://github.com/OpenVoiceOS/)
  or [LLMs](https://github.com/OpenVoiceOS/ovos-persona).

---

## 🔌 Modular Design with Plugins

HiveMind is designed to be modular, allowing you to customize its behavior through plugins managed by the **HiveMind Plugin Manager**.

- **Transport Mechanism** 🚚: The protocol does not specify **how** messages are transported; this is implemented via **network protocol plugins** (e.g., Websockets, HTTP).
- **Payload Handling** 🤖 : The protocol does not dictate **who** handles the messages; this is implemebted via **agent protocol plugins** (e.g., OVOS, Persona).
- **Message Format** 📦: The protocol supports **JSON data** modeled after the `Message` [structure from OVOS](https://jarbashivemind.github.io/HiveMind-community-docs/13_mycroft/) and **binary** data; what happens to the received binary data is implemented via **binary data protocol plugins** (e.g., process incoming audio).
- **Database**: 🗃️ how client credentials are stored is implemented via **database plugins** (e.g., JSON, SQLite, Redis).

---

## 📖 Protocol Configuration

HiveMind Core now supports a configuration file, making it easier for users to define server settings and reduce the need for complex command-line arguments. 

> 💡 The configuration file is stored at `~/.config/hivemind-core/server.json`

The default configuration

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
    "module": "hivemind-json-db-plugin",
    "hivemind-json-db-plugin": {
      "name": "clients",
      "subfolder": "hivemind-core"
    }
  }
}
```

### Policy Admission Chain

Every inbound message passes through an ordered **policy admission chain** before reaching the agent bus. See [issue #85](https://github.com/JarbasHiveMind/HiveMind-core/issues/85) for the full spec.

**How it works:**

1. `ClientACLPolicy` is **always prepended** to the chain and cannot be removed by configuration. It enforces the per-client `allowed_types` whitelist: if `message.msg_type` is not in the client's `allowed_types`, the message is denied. Admin clients bypass the whitelist entirely. — `hivemind_core/policy.py:174`
2. Configured plugins in `policy.chain` run after `ClientACLPolicy`, in order. Each plugin can deny the message or contribute mutations applied before the next plugin runs.
3. The chain is **always fail-closed**. Any unhandled exception in a policy becomes `Verdict.deny("policy_error", ...)`. There is no operator knob to override this. — `hivemind_core/policy.py:36`
4. If the chain fails to build at startup, a `DenyAllPolicy` fallback is installed, rejecting every message with `code="policy_chain_unavailable"` until configuration is fixed. — `hivemind_core/policy.py:151`

**Denied messages** receive a `hive.policy.denied` BUS response with payload:

```json
{
  "denied_type": "<msg_type or 'binary'>",
  "code": "<verdict code>",
  "reason": "<human-readable reason>",
  "data": {}
}
```

`handle_inject_agent_msg` runs `policy_chain.review()` then `policy_chain.observe()` for every accepted message. `handle_binary_message` runs `policy_chain.review_binary()`. — `hivemind_core/protocol.py:908`, `hivemind_core/protocol.py:457`

**ACL model — whitelist-only, deny-by-default:**

- `allowed_types` is the only ACL field on `HiveMindClientConnection`. There is no message blacklist. — `hivemind_core/protocol.py:92`
- A freshly created client (via `add-client`) has an **empty** `allowed_types` list and will be denied all messages until the operator explicitly grants types with `allow-msg`.
- Admin clients (`is_admin=True`) bypass `ClientACLPolicy` entirely.

To grant a message type:

```bash
$ hivemind-core allow-msg "recognizer_loop:utterance" 1
$ hivemind-core allow-msg "speak" 1
```

**Removing a type** (mutates `allowed_types`; not deprecated):

```bash
$ hivemind-core blacklist-msg "speak" 1
```

**Skill and intent filtering** are OVOS-specific concerns handled by `OVOSAgentPolicy` (shipped with `hivemind-ovos-agent-plugin`, the default `agent_protocol`). The CLI commands `blacklist-skill`, `allow-skill`, `blacklist-intent`, and `allow-intent` are preserved for backwards compatibility but emit a deprecation warning and write through `Client.metadata` rather than a first-class field. — `hivemind_core/scripts.py:464`

To add additional policies, extend the `policy.chain` list with plugin module names:

```json
"policy": {
  "chain": [
    {"module": "hivemind-ovos-agent-policy"},
    {"module": "hivemind-intent-quota-policy", "config": {"limit": 100}}
  ]
}
```

Drop `hivemind-ovos-agent-policy` from the list only if you are running a non-OVOS agent backend.


---

## 🛰️  Quick Start

To get started, HiveMind Core provides a command-line interface (CLI) for managing clients, permissions, and connections.

### Installation

```bash
pip install hivemind-core
```

### Adding a Satellite

Add credentials for each satellite device:

```bash
$ hivemind-core add-client --db-backend sqlite 
Database backend: SQLiteDB
Credentials added to database!

Node ID: 3
Friendly Name: HiveMind-Node-2
Access Key: 42caf3d2405075fb9e7a4e1ff44e4c4f
Password: 5ae486f7f1c26bd4645bd052e4af3ea3
Encryption Key: f46351c54f61a715
WARNING: Encryption Key is deprecated, only use if your client does not support password
```

**NOTE**: You will need to provide this information on the client devices to connect.

### Running the Server

Start the HiveMind Core server to accept connections:

```bash
$ hivemind-core listen
```

---

## 🛠️ Commands Overview

HiveMind Core CLI supports the following commands:

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
  delete-client        remove credentials for a client
  list-clients         list clients and credentials
  listen               start listening for HiveMind connections
  make-admin           grant administrator privileges to a client
  revoke-admin         revoke administrator privileges from a client
  rename-client        rename a client in the database
  allow-intent         (deprecated) remove an intent from a client blacklist
  allow-skill          (deprecated) remove a skill from a client blacklist
  blacklist-intent     (deprecated) blacklist an intent for a client
  blacklist-skill      (deprecated) blacklist a skill for a client
```

For detailed help on each command, use `--help` (e.g., `hivemind-core add-client --help`).

> 💡 **Tip**: if you don't specify the numeric client_id in your commands you will be prompted for it interactively

<details>
  <summary>Click for more details</summary>

---

### `add-client`

Add credentials for a new client that will connect to the HiveMind instance.

```bash
$ hivemind-core add-client --name "satellite_1" --access-key "mykey123" --password "mypass"
```

- **When to use**:  
  Use this command when setting up a new HiveMind client (e.g., Raspberry Pi, IoT device). Provide credentials for
  secure communication with the server.
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
  Use this command to view or inspect all registered clients, helpful for debugging or managing devices connected to
  HiveMind.

---

### `rename-client`

Rename a registered client.

```bash
$ hivemind-core rename-client "new name" 1
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
  Use this command to revoke a client’s access, for example, when a device is lost, no longer in use, or compromised.

---

### `allow-msg`

Grant a specific message type to a client’s `allowed_types` whitelist. New clients have an **empty** whitelist and are denied all messages until at least one type is granted.

```bash
$ hivemind-core allow-msg "recognizer_loop:utterance" 1
$ hivemind-core allow-msg "speak" 1
```

- **When to use**:  
  Use this command after `add-client` to grant the message types the client needs. Without any `allow-msg` calls the client is effectively locked out (deny-by-default).

---

### `blacklist-msg`

Revoke specific message types from being allowed to be sent by a client.

```bash
$ hivemind-core blacklist-msg "speak"
```

- **When to use**:  
  Use this command to prevent specific message types from being sent by a client, adding a layer of control over
  communication.

---

### `blacklist-skill` / `allow-skill` / `blacklist-intent` / `allow-intent` (deprecated)

> **Deprecated.** These commands emit a deprecation warning to stderr and write through `Client.metadata` rather than a first-class field. Skill and intent filtering is an OVOS-specific concern now handled by `OVOSAgentPolicy` (shipped with `hivemind-ovos-agent-plugin`). The commands are preserved for backwards compatibility with existing deployment scripts. — `hivemind_core/scripts.py:464`

```bash
$ hivemind-core blacklist-skill "skill-weather" 1   # writes Client.metadata["skill_blacklist"]
$ hivemind-core allow-skill "skill-weather" 1
$ hivemind-core blacklist-intent "intent.check_weather" 1  # writes Client.metadata["intent_blacklist"]
$ hivemind-core allow-intent "intent.check_weather" 1
```

For new deployments, configure `OVOSAgentPolicy` directly or set `Client.metadata["skill_blacklist"]` / `Client.metadata["intent_blacklist"]` via `add-client --metadata`.

---

### `listen`

Start the HiveMind instance to listen for client connections.

```bash
$ hivemind-core listen
```

- **When to use**:  
  Use this command to start the HiveMind instance, enabling it to accept connections from clients (e.g., satellite
  devices). Configure the host, port, and security options as needed.

---

</details>


---

## 🧩 Plugins Overview

| **Category**         | **Plugin**                                                                                   | **Description**                                                                                                                                                                                          |
|----------------------|----------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Network Protocol** | [hivemind-websocket-protocol](https://github.com/JarbasHiveMind/hivemind-websocket-protocol) | Provides WebSocket-based communication for Hivemind, enabling real-time data exchange.                                                                                                                   |
|   | [hivemind-http-protocol](https://github.com/JarbasHiveMind/hivemind-http-protocol) | Provides HTTP-based communication for Hivemind, ideal for when a persistent connected is undesirable/not-possible                                                                                                                   |
| **Binary Protocol**  | [hivemind-audio-binary-protocol](https://github.com/JarbasHiveMind/hivemind-audio-binary-protocol)                     | Listens for incoming audio and processes it using the [ovos-plugin-manager](https://github.com/OpenVoiceOS/ovos-plugin-manager), enabling seamless interaction between Hivemind and audio input systems. |
| **Agent Protocol**   | [OpenVoiceOS](https://github.com/OpenVoiceOS/ovos-core)                                      | Integration with OpenVoiceOS, facilitated by [ovos-bus-client](https://github.com/OpenVoiceOS/ovos-bus-client/blob/dev/ovos_bus_client/hpm.py), enabling seamless communication with OVOS systems.                                       |
|                      | [Persona](https://github.com/OpenVoiceOS/ovos-persona)                                | LLM (Large Language Model) integration provided by [ovos-persona](https://github.com/OpenVoiceOS/ovos-persona/blob/dev/ovos_persona/hpm.py), works with all OpenAI server compatible projects.                                         |
| **Database**         | [hivemind-sqlite-database](https://github.com/JarbasHiveMind/hivemind-sqlite-database)       | SQLite-based database solution for managing local data within Hivemind applications.                                                                                                                     |
|                      | [hivemind-redis-database](https://github.com/JarbasHiveMind/hivemind-redis-database)         | Redis integration for scalable, in-memory database solutions with fast data access.                                                                                                                      |
|                      | [hivemind-json-database](https://github.com/TigreGotico/json_database/pull/7)                | A JSON-based database plugin provided by [json-database](https://github.com/TigreGotico/json_database), offering lightweight storage and retrieval using JSON format.                                    |

---

## 💬 Clients Overview

| **Category**   | **Client**                                                                      | **Description**                                                                                              |
|----------------|---------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|
| **Satellites** | [Voice Satellite](https://github.com/OpenJarbas/HiveMind-voice-sat)             | Standalone OVOS *local* audio stack for Hivemind.                                                            |
|                | [Voice Relay](https://github.com/JarbasHiveMind/HiveMind-voice-relay)           | Lightweight audio satellite, STT/TTS processed *server* side, **requires** `hivemind-audio-binary-protocol`.              |
|                | [Mic Satellite](https://github.com/JarbasHiveMind/hivemind-mic-satellite)       | Only VAD runs on device, audio streamed and fully processed *server* side, **requires** `hivemind-audio-binary-protocol`. |
|                | [Web Chat](https://github.com/OpenJarbas/HiveMind-webchat)                      | *Client-side* browser Hivemind connection for web-based communication.                                       |
| **Bridges**    | [Mattermost Bridge](https://github.com/OpenJarbas/HiveMind_mattermost_bridge)   | Bridge for talking to Hivemind via Mattermost                                                                |
|                | [Matrix Bridge](https://github.com/JarbasHiveMind/HiveMind-matrix-bridge)       | Bridge for talking to Hivemind via Matrix                                                                    |
|                | [DeltaChat Bridge](https://github.com/JarbasHiveMind/HiveMind-deltachat-bridge) | Bridge for talking to Hivemind via DeltaChat                                                                 |

---

## 🚀 Next Steps

- Visit the [documentation](https://jarbashivemind.github.io/HiveMind-community-docs) for detailed guides.
- Join the [HiveMind Matrix Chat](https://matrix.to/#/#jarbashivemind:matrix.org) for support and updates.
- Explore additional plugins and expand your HiveMind ecosystem.

---

## ⚖️ License

HiveMind-core is released under a **dual-license model**:

### AGPL-3.0 (Open Source)

Starting with **version 4.0**, HiveMind-core is licensed under the **GNU AGPL-3.0**.

All prior releases remain available under **Apache-2.0**. 

You may use, study, and modify HiveMind-core under the AGPL-3.0 license.  

If you modify HiveMind-core or build derivative works, you must publish the complete corresponding source code of those modifications.

Redistributing HiveMind-core (including Docker images or docker-compose bundles) requires making its source code accessible to users.


---

### Commercial License

Commercial use of HiveMind-core — including proprietary integrations, internal services, or any deployment where AGPL disclosure obligations are impractical — requires a **commercial license**. 

Detailed information is available in [COMMERCIAL-TERMS.md](./COMMERCIAL-TERMS.md)

> 💡 **Non-profits and permissively licensed projects** (MIT, BSD, Apache-2.0, etc.) are eligible for **no-cost commercial licenses**. If you fall into this category, your contributions to the ecosystem are considered sufficient, please get in touch.

Contact: **[jarbasai@mailfence.com](mailto:jarbasai@mailfence.com)** for licensing.

---


### Trademark and Branding Restrictions

The names **HiveMind-core**, **Hivemind Protocol**, the HiveMind logos, and any “HiveMind Compatible / Powered by HiveMind” marks are protected trademarks.

You may not use these trademarks in commercial products, marketing materials, documentation, or compatibility claims without a trademark license.

Trademarks remain restricted regardless of AGPL compliance.

---

## 🤝 Contribution Policy

HiveMind-core is maintained under a **dual-license model** (AGPL/commercial). To preserve license flexibility and consistent ownership of the codebase, HiveMind-core **does not accept external code contributions**.

1. **No Contributor License Agreement (CLA)**

   * HiveMind-core does **not require or accept a CLA**.
   * This avoids administrative overhead and prevents asymmetry between contributors and the project owner.
   * It ensures the project can **enforce both AGPL and commercial licensing** without ambiguity.

2. **Why external contributions are restricted**

   * Maintaining ownership over the codebase allows the maintainer to:

     * Offer a **commercial license** without conflicts.
     * Control relicensing or dual-licensing strategy.
     * Protect the integrity of HiveMind-core for commercial and open-source users alike.

3. **Open community participation**

   * While code contributions are not accepted, the community is encouraged to:

     * **Report bugs** via GitHub issues.
     * **Request features** or improvements.
     * **Discuss ideas** in the [Matrix chat](https://matrix.to/#/#jarbashivemind:matrix.org).
