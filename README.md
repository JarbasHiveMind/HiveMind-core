# HiveMind Core

HiveMind is a flexible [protocol](https://jarbashivemind.github.io/HiveMind-community-docs/04_protocol/) that
facilitates communication and collaboration among devices and AI agents within a
unified network. It enables lightweight devices, called **satellites**, to connect to a central hub, with customizable
permissions and centralized control.

HiveMind also
supports [hierarchical hub-to-hub connections](https://jarbashivemind.github.io/HiveMind-community-docs/15_nested/),
creating powerful,
scalable smart environments.

Initially developed as part of the [OpenVoiceOS (OVOS)](https://github.com/OpenVoiceOS/) ecosystem, HiveMind is
adaptable to various AI backend systems.

For more details and demonstrations, check
our [YouTube channel](https://www.youtube.com/channel/UCYoV5kxp2zrH6pnoqVZpKSA/).

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

HiveMind is designed to be modular, allowing you to customize its behavior through plugins managed by the **HiveMind
Plugin Manager**.

- **Transport Mechanism** 🚚: The protocol does not specify **how** messages are transported; this is implemented via **network protocol plugins**.
- **Payload Handling** 🤖 : The protocol does not dictate **who** handles the messages; this is implemebted via **agent protocol plugins**.
- **Message Format** 📦: The protocol supports **JSON data** modeled after the `Message` [structure from OVOS](https://jarbashivemind.github.io/HiveMind-community-docs/13_mycroft/) and **binary** data; what happens to the received binary data is implemented via **binary data protocol plugins**.
- **Database**: 🗃️ how client credentials are stored is implemented via **database plugins**

---

## 📖 Anatomy of a HiveMind Server

In addition to implementing the [hivemind protocol](https://jarbashivemind.github.io/HiveMind-community-docs/04_protocol/), a HiveMind server uses configurable plugins for other key components:

1. **Database**: Stores client credentials and settings (e.g., JSON, SQLite, Redis).
2. **Network Protocol**: Determines how devices connect to the server (e.g., Websockets, HTTP).
3. **Agent Protocol**: Defines how the server processes and responds to messages (e.g., OVOS, Persona).
4. **Binary Protocol**: Specifies what to do you the received binary data (e.g., process incoming audio).

Each component can be extended or replaced using plugins, providing unparalleled flexibility for your specific use case.

### Protocol Configuration

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
    "module": "hivemind-websocket-plugin",
    "hivemind-websocket-plugin": {
      "host": "0.0.0.0",
      "port": 5678,
      "ssl": false,
      "cert_dir": "/path/to/xdg/data/hivemind",
      "cert_name": "hivemind"
    }
  },
  "database": {
    "module": "hivemind-json-db-plugin",
    "hivemind-json-db-plugin": {
      "name": "clients",
      "folder": "hivemind-core"
    }
  }
}
```


---

## 🛰️  Quick Start

To get started, HiveMind Core provides a command-line interface (CLI) for managing clients, permissions, and
connections.

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

## 🧩 Plugins Overview

| **Category**         | **Plugin**                                                                                   | **Description**                                                                                                                                                                                          |
|----------------------|----------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Network Protocol** | [hivemind-websocket-protocol](https://github.com/JarbasHiveMind/hivemind-websocket-protocol) | Provides WebSocket-based communication for Hivemind, enabling real-time data exchange.                                                                                                                   |
| **Binary Protocol**  | [hivemind-listener](https://github.com/JarbasHiveMind/hivemind-listener)                     | Listens for incoming audio and processes it using the [ovos-plugin-manager](https://github.com/OpenVoiceOS/ovos-plugin-manager), enabling seamless interaction between Hivemind and audio input systems. |
| **Agent Protocol**   | [OpenVoiceOS](https://github.com/OpenVoiceOS/ovos-core)                                      | Integration with OpenVoiceOS, facilitated by [ovos-bus-client](https://github.com/OpenVoiceOS/ovos-bus-client), enabling seamless communication with OVOS systems.                                       |
|                      | [Persona](https://github.com/JarbasHiveMind/hivemind-persona)                                | LLM (Large Language Model) integration powered by [ovos-persona](https://github.com/OpenVoiceOS/ovos-persona), works with all OpenAI server compatible projects.                                         |
| **Database**         | [hivemind-sqlite-database](https://github.com/JarbasHiveMind/hivemind-sqlite-database)       | SQLite-based database solution for managing local data within Hivemind applications.                                                                                                                     |
|                      | [hivemind-redis-database](https://github.com/JarbasHiveMind/hivemind-redis-database)         | Redis integration for scalable, in-memory database solutions with fast data access.                                                                                                                      |
|                      | [hivemind-json-database](https://github.com/TigreGotico/json_database/pull/7)                | A JSON-based database plugin provided by [json-database](https://github.com/TigreGotico/json_database), offering lightweight storage and retrieval using JSON format.                                    |

## 💬 Clients Overview

| **Category**   | **Client**                                                                      | **Description**                                                                                              |
|----------------|---------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|
| **Satellites** | [Voice Satellite](https://github.com/OpenJarbas/HiveMind-voice-sat)             | Standalone OVOS *local* audio stack for Hivemind.                                                            |
|                | [Voice Relay](https://github.com/JarbasHiveMind/HiveMind-voice-relay)           | Lightweight audio satellite, STT/TTS processed *server* side, **requires** `hivemind-listener`.              |
|                | [Mic Satellite](https://github.com/JarbasHiveMind/hivemind-mic-satellite)       | Only VAD runs on device, audio streamed and fully processed *server* side, **requires** `hivemind-listener`. |
|                | [Web Chat](https://github.com/OpenJarbas/HiveMind-webchat)                      | *Client-side* browser Hivemind connection for web-based communication.                                       |
| **Bridges**    | [Mattermost Bridge](https://github.com/OpenJarbas/HiveMind_mattermost_bridge)   | Bridge for talking to Hivemind via Mattermost                                                                |
|                | [Matrix Bridge](https://github.com/JarbasHiveMind/HiveMind-matrix-bridge)       | Bridge for talking to Hivemind via Matrix                                                                    |
|                | [DeltaChat Bridge](https://github.com/JarbasHiveMind/HiveMind-deltachat-bridge) | Bridge for talking to Hivemind via DeltaChat                                                                 |

---

## 🛠️ Commands Overview

HiveMind Core CLI supports the following commands:

```bash
$ hivemind-core --help
Usage: hivemind-core [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  add-client        add credentials for a client
  allow-intent      remove intents from a client blacklist
  allow-msg         allow message types to be sent from a client
  allow-skill       remove skills from a client blacklist
  blacklist-intent  blacklist intents from being triggered by a client
  blacklist-msg     blacklist message types from being sent from a client
  blacklist-skill   blacklist skills from being triggered by a client
  delete-client     remove credentials for a client
  list-clients      list clients and credentials
  listen            start listening for HiveMind connections
  rename-client     Rename a client in the database
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

By default only some messages are allowed, extra messages can be allowed per client

Allow specific message types to be sent by a client.

```bash
$ hivemind-core allow-msg "speak"
```

- **When to use**:  
  Use this command to enable certain message types, particularly when extending a client’s communication capabilities (
  e.g., allowing TTS commands).

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

### `blacklist-skill`

Prevent a specific skill from being triggered by a client.

```bash
$ hivemind-core blacklist-skill "skill-weather" 1
```

- **When to use**:  
  Use this command to restrict a client’s access to particular skills, such as preventing a device from accessing
  certain skills for safety or appropriateness.

---

### `allow-skill`

Remove a skill from a client’s blacklist, allowing it to be triggered.

```bash
$ hivemind-core allow-skill "skill-weather" 1
```

- **When to use**:  
  If restrictions on a skill are no longer needed, use this command to reinstate access to the skill.

---

### `blacklist-intent`

Block a specific intent from being triggered by a client.

```bash
$ hivemind-core blacklist-intent "intent.check_weather" 1
```

- **When to use**:  
  Use this command to block a specific intent from being triggered by a client. This is useful for managing permissions
  in environments with shared skills.

---

### `allow-intent`

Remove a specific intent from a client’s blacklist.

```bash
$ hivemind-core allow-intent "intent.check_weather" 1
```

- **When to use**:  
  Use this command to re-enable access to previously blocked intents, restoring functionality for the client.

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

## 🚀 Next Steps

- Visit the [documentation](https://jarbashivemind.github.io/HiveMind-community-docs) for detailed guides.
- Join the [HiveMind Matrix Chat](https://matrix.to/#/#jarbashivemind:matrix.org) for support and updates.
- Explore additional plugins and expand your HiveMind ecosystem.

---

## 🤝 Contributing

HiveMind Core is open source and welcomes contributions from the community. If you’d like to contribute, here’s how you
can get started:

1. **Fork the Repository**:  
   Fork the [HiveMind Core GitHub repository](https://github.com/JarbasHiveMind/HiveMind-core).

2. **Open an Issue**:  
   Report bugs or suggest features by [creating an issue](https://github.com/JarbasHiveMind/HiveMind-core/issues).

3. **Submit Pull Requests**:  
   Develop your features or bug fixes in a feature branch and submit a pull request to the main repository.

4. **Join the Discussion**:  
   Participate in the [Matrix chat](https://matrix.to/#/#jarbashivemind:matrix.org) to share ideas and collaborate with
   the community.

As HiveMind continues to grow, there are several exciting projects on the horizon that could benefit from community
involvement. 

🚧 Here are some beginner-friendly projects where you can contribute: 🚧

- **Wyoming Binary Protocol** 🏡: Translate binary payloads to the Wyoming protocol, using Wyoming servers instead of
  OVOS plugins.
- **Assist Protocol Agent** 🏡: Develop an agent that communicates with Home Assistant, enabling seamless integration of
  HiveMind satellites with Home Assistant.
- **HTTP / MQTT Network Protocols** 🌐: Implement network protocols specifically designed for IoT devices, enhancing
  connectivity and communication within smart environments.
- **GGWave Network Protocol** 🎶: Create a solution for HiveMind communication via sound, allowing for networkless
  systems to interact using audio signals.

---

## ⚖️ License

HiveMind is open-source software, licensed under the [Apache 2.0 License](LICENSE).





