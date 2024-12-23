# HiveMind Core

HiveMind is an extension of [OpenVoiceOS (OVOS)](https://github.com/OpenVoiceOS/), the open-source voice assistant
platform. It enables you to extend a single instance of `ovos-core` across multiple devices, even those with limited
hardware capabilities that can't typically run OVOS.

Demo videos in [youtube](https://www.youtube.com/channel/UCYoV5kxp2zrH6pnoqVZpKSA/)

---

## 🌟 Key Features

- **Expand Your Ecosystem**: Seamlessly connect lightweight or legacy devices as satellites to a central OVOS hub.
- **Centralized Control**: Manage and monitor all connected devices from a single hivemind-core instance.
- **Fine-Grained Permissions**: Control skills, intents, and message access per client.
- **Flexible Database Support**: Choose from JSON, SQLite, or Redis to fit your setup.

---

## 📖 Documentation & Community

- 📚 **Documentation**: [HiveMind Docs](https://jarbashivemind.github.io/HiveMind-community-docs)
- 💬 **Chat**: Join the [HiveMind Matrix Chat](https://matrix.to/#/#jarbashivemind:matrix.org) for news, support, and
  discussion.

---

## 🚀 Quick Start

To get started, HiveMind Core provides a command-line interface (CLI) for managing clients, permissions, and
connections.

### Installation

```bash
pip install hivemind-core
```

### Adding a satellite

Add credentials for each satellite device

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

**NOTE**: you will need to provide this info on the client devices in order to connect

### Running the Server

Start the HiveMind Core server to accept connections:

```bash
$ hivemind-core listen --port 5678
```

---

## 📦 Database Backends

HiveMind-Core supports multiple database backends to store client credentials and settings. Each has its own use case:

| Backend            | Use Case                                       | Default Location                            | Command Line options                               |
|--------------------|------------------------------------------------|---------------------------------------------|----------------------------------------------------|
| **JSON** (default) | Simple, file-based setup for local use         | `~/.local/share/hivemind-core/clients.json` | Configurable via `--db-name` and `--db-folder`     |
| **SQLite**         | Lightweight relational DB for single instances | `~/.local/share/hivemind-core/clients.db`   | Configurable via `--db-name` and `--db-folder`     |
| **Redis**          | Distributed, high-performance environments     | `localhost:6379`                            | Configurable via `--redis-host` and `--redis-port` |

**How to Choose?**

- For **scalability** or multi-instance setups, use Redis.
- For **simplicity** or single-device environments, use SQLite.
- For **development** or to be able to edit the database by hand, use JSON.

---

### 🔑 Permissions

HiveMind Core uses a flexible **RBAC inspired system** where permissions are assigned directly to each client. 

Instead of predefined roles or groups, each client’s configuration determines their access.

1. **Default Permissions**  
   - **Bus Messages**: Denied by default, except for a core set of universally allowed messages:  
     ```python
     ["recognizer_loop:utterance", "recognizer_loop:record_begin",
      "recognizer_loop:record_end", "recognizer_loop:audio_output_start",
      "recognizer_loop:audio_output_end", "recognizer_loop:b64_transcribe",
      "speak:b64_audio", "ovos.common_play.SEI.get.response"]
     ```  
     The main message, `recognizer_loop:utterance`, enables universal natural language instructions for seamless integration.
   - **Skills & Intents**: Allowed by default but can be blacklisted for specific clients.

2. **Granular Controls**  
   - Per-client **allowlists** for bus messages.  
   - **Blacklists** for skills or intents to restrict access.  

3. **Emergent Roles**  
   - While no explicit roles exist, configurations can emulate roles like "basic client" (default permissions) or "restricted client" (blacklisted skills/intents).

#### 👤 Example Use Cases  

1. **General AI Integration**  
   - A basic client is configured with the default allowed message types, enabling it to send natural language instructions (`recognizer_loop:utterance`).  
   - This setup allows seamless integration of third-party AI systems or assistants.  

2. **Custom Permissions for Specialized Clients**  
   - An IoT device is allowed specific bus messages (e.g., `temperature.set`) to control heating systems.  
   - Sensitive intents, such as `shutdown` or `reboot`, are blacklisted to prevent misuse.  

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
$ hivemind-core add-client --name "satellite_1" --access-key "mykey123" --password "mypass" --db-backend json
```

- **When to use**:  
  Use this command when setting up a new HiveMind client (e.g., Raspberry Pi, IoT device). Provide credentials for secure communication with the server.

---

### `list-clients`

List all registered clients and their credentials.

```bash
$ hivemind-core list-clients --db-backend json
```

- **When to use**:  
  Use this command to view or inspect all registered clients, helpful for debugging or managing devices connected to HiveMind.

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
  Use this command to enable certain message types, particularly when extending a client’s communication capabilities (e.g., allowing TTS commands).

---

### `blacklist-msg`

Revoke specific message types from being allowed to be sent by a client.

```bash
$ hivemind-core blacklist-msg "speak"
```

- **When to use**:  
  Use this command to prevent specific message types from being sent by a client, adding a layer of control over communication.

---

### `blacklist-skill`

Prevent a specific skill from being triggered by a client.

```bash
$ hivemind-core blacklist-skill "skill-weather" 1
```

- **When to use**:  
  Use this command to restrict a client’s access to particular skills, such as preventing a device from accessing certain skills for safety or appropriateness.

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
  Use this command to block a specific intent from being triggered by a client. This is useful for managing permissions in environments with shared skills.

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
$ hivemind-core listen --ovos_bus_address "127.0.0.1" --port 5678
```

- **When to use**:  
  Use this command to start the HiveMind instance, enabling it to accept connections from clients (e.g., satellite devices). Configure the host, port, and security options as needed.

---

</details>

#### Running in Distributed Environments

By default, HiveMind listens for the OpenVoiceOS bus on `127.0.0.1`. When running in distributed environments (e.g.,
Kubernetes), use the `--ovos_bus_address` and `--ovos_bus_port` options to specify the bus address and port.


---

## 🧩 HiveMind Ecosystem

### Minds

This is the "brain" you want to host behind the hivemind protocol, it can be anything you want but by default we
assume [OpenVoiceOS](https://openvoiceos.org) is being used

- **HiveMind Core** (this repository): The central hub for managing connections and routing messages between devices.
- [Hivemind Listener](https://github.com/JarbasHiveMind/HiveMind-listener) - an extension of `hivemind-core` for
  streaming *audio* from satellites
- [Persona](https://github.com/JarbasHiveMind/HiveMind-persona) - run
  a [persona](https://github.com/OpenVoiceOS/ovos-persona) (eg. LLM). *text* input only

### Client Libraries

- [HiveMind WebSocket Client](https://github.com/JarbasHiveMind/hivemind_websocket_client)
- [HiveMind JS](https://github.com/JarbasHiveMind/HiveMind-js)

### Terminals

- [Voice Satellite](https://github.com/OpenJarbas/HiveMind-voice-sat)  (standalone OVOS *local* audio stack)
- [Voice Relay](https://github.com/JarbasHiveMind/HiveMind-voice-relay)  (lightweight audio satellite, STT/TTS
  processed *server* side, **requires** `hivemind-listener`)
- [Mic Satellite](https://github.com/JarbasHiveMind/hivemind-mic-satellite) (only VAD runs on device, audio streamed
  and fully processed *server* side, **requires** `hivemind-listener`)
- [Web Chat](https://github.com/OpenJarbas/HiveMind-webchat) (*client-side* browser hivemind connection)
- [Flask Chatroom](https://github.com/JarbasHiveMind/HiveMind-flask-template)  (**boilerplate template** - *server-side*
  hivemind connection)

### Bridges

- [Mattermost Bridge](https://github.com/OpenJarbas/HiveMind_mattermost_bridge)
- [DeltaChat Bridge](https://github.com/JarbasHiveMind/HiveMind-deltachat-bridge)

---

## Hivemind Server Comparison

When building your HiveMind servers there are many ways to go about it, with many optional components

Common setups:

- **OVOS Device**, a full OVOS install without hivemind *(for reference only)*
- **Hivemind Device**, a OVOS device also running hivemind, eg. a Mark2 with it's own satellites.
- **Hivemind Skills Server**, a minimal HiveMind server that satellites can connect to, supports **text** utterances
  only
- **Hivemind Sound Server**, a HiveMind server that supports **text** utterances and **streaming audio**
- **Hivemind Persona Server**, exposes a `ovos-persona` (eg. an LLM) that satellites can connect to, without
  running `ovos-core`.

The table below illustrates the most common setups for a OVOS based Mind, each column represents a running OVOS/HiveMind
service on your server

|                             | **hivemind-core** | **hivemind-listener** | **ovos-core** | **ovos-audio** | **ovos-listener** | **hivemind-persona** |
|-----------------------------|-------------------|-----------------------|---------------|----------------|-------------------|----------------------|
| **OVOS Device**             | ❌                 | ❌                     | ✔️            | ✔️             | ✔️                | ❌                    | 
| **Hivemind Device**         | ✔️                | ❌                     | ✔️            | ✔️             | ✔️                | ❌                    | 
| **Hivemind Skills Server**  | ✔️                | ❌                     | ✔️            | ❌              | ❌                 | ❌                    | 
| **Hivemind Sound Server**   | ❌                 | ✔️                    | ✔️            | ❌              | ❌                 | ❌                    | 
| **Hivemind Persona Server** | ❌                 | ❌                     | ❌             | ❌              | ❌                 | ✔️                   | 

The table below indicates compatibility for each of the setups described above with the most common voice satellites,
each column corresponds to a different satellite

|                             | **voice satellite** | **voice relay** | **mic satellite** |
|-----------------------------|---------------------|-----------------|-------------------|
| **OVOS Device**             | ❌                   | ❌               | ❌                 |
| **Hivemind Device**         | ✔️                  | ✔️              | ❌                 |
| **Hivemind Skills Server**  | ✔️                  | ❌               | ❌                 |
| **Hivemind Sound Server**   | ✔️                  | ✔️              | ✔️                |
| **Hivemind Persona Server** | ✔️                  | ❌               | ❌                 |

---

## OVOS Plugins Compatibility

Hivemind leverages [ovos-plugin-manager](), bringing compatibility with hundreds of plugins.

> 💡 **Tip**: OVOS plugins can be used both on *client* and *server* side

| Plugin Type         | Description                                             | Documentation                                                                                   |
|---------------------|---------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| Microphone          | Captures voice input                                    | [Microphone Documentation](https://openvoiceos.github.io/ovos-technical-manual/310-mic_plugins)    |
| VAD                 | Voice Activity Detection                                | [VAD Documentation](https://openvoiceos.github.io/ovos-technical-manual/311-vad_plugins/)           |
| WakeWord            | Detects wake words for interaction                      | [WakeWord Documentation](https://openvoiceos.github.io/ovos-technical-manual/312-wake_word_plugins/)       |
| STT                 | Speech-to-text (STT)                                    | [STT Documentation](https://openvoiceos.github.io/ovos-technical-manual/313-stt_plugins/)           |
| TTS                 | Text-to-speech (TTS)                                    | [TTS Documentation](https://openvoiceos.github.io/ovos-technical-manual/320-tts_plugins/)            |
| G2P                 | Grapheme-to-phoneme (G2P)<br>used to simulate mouth movements | [G2P Documentation](https://openvoiceos.github.io/ovos-technical-manual/321-g2p_plugins/)           |
| Media Playback      | Enables media playback (e.g., "play Metallica")         | [Media Playback Documentation](https://openvoiceos.github.io/ovos-technical-manual/371-media_plugins/) |
| OCP Plugins         | Provides playback support for URLs (e.g., YouTube)      | [OCP Plugins Documentation](https://openvoiceos.github.io/ovos-technical-manual/370-ocp_plugins/)   |
| Audio Transformers  | Parse/Modify *audio* before speech-to-text (STT)        | [Audio Transformers Documentation](https://openvoiceos.github.io/ovos-technical-manual/330-transformer_plugins/) |
| Utterance Transformers | Parse/Modify *text utterance* before Intent Parsing  | [Utterance Transformers Documentation](https://openvoiceos.github.io/ovos-technical-manual/330-transformer_plugins/) |
| Metadata Transformers  | Parse/Modify *Session data* before Intent Parsing    | [Metadata Transformers Documentation](https://openvoiceos.github.io/ovos-technical-manual/330-transformer_plugins/) |
| Dialog Transformers | Parse/Modify *text utterance* before text-to-speech (TTS) | [Dialog Transformers Documentation](https://openvoiceos.github.io/ovos-technical-manual/330-transformer_plugins/) |
| TTS Transformers    | Parse/Modify *audio* after text-to-speech (TTS)         | [TTS Transformers Documentation](https://openvoiceos.github.io/ovos-technical-manual/330-transformer_plugins/) |
| PHAL                | Provides platform-specific support (e.g., Mark 1)       | [PHAL Documentation](https://openvoiceos.github.io/ovos-technical-manual/340-PHAL)                |

### Client side plugins

The tables below illustrates how plugins from the OVOS ecosystem relate to the various satellites and where they should
be installed and configured

<details>
  <summary>Click for more details</summary>


**Audio input**:

| Supported Plugins                 | **Microphone**   | **VAD**          | **Wake Word**      | **STT**          |
|-----------------------------------|------------------|------------------|--------------------|------------------|
| **HiveMind Voice Satellite**      | ✔️<br>(Required) | ✔️<br>(Required) | ✔️<br>(Required *) | ✔️<br>(Required) | 
| **HiveMind Voice Relay**          | ✔️<br>(Required) | ✔️<br>(Required) | ✔️<br>(Required)   | 📡<br>(Remote)   | 
| **HiveMind Microphone Satellite** | ✔️<br>(Required) | ✔️<br>(Required) | 📡<br>(Remote)     | 📡<br>(Remote)   | 

* can be skipped
  with [continuous listening mode](https://openvoiceos.github.io/ovos-technical-manual/speech_service/#modes-of-operation)

**Audio output**:

| Supported Plugins                 | **TTS**          | **Media Playback** | **OCP extractors** | 
|-----------------------------------|------------------|--------------------|--------------------| 
| **HiveMind Voice Satellite**      | ✔️<br>(Required) | ✔️<br>(Optional)   | ✔️<br>(Optional)   |  
| **HiveMind Voice Relay**          | 📡<br>(Remote)   | ✔️<br>(Optional)   | ✔️<br>(Optional)   | 
| **HiveMind Microphone Satellite** | 📡<br>(Remote)   | ✔️<br>(Optional)   | ✔️<br>(Optional)   |  

**Transformers**:

| Supported Plugins                 | **Audio**          | **Utterance**      | **Metadata**       | **Dialog**         | **TTS**            |
|-----------------------------------|--------------------|--------------------|--------------------|--------------------|--------------------|
| **HiveMind Voice Satellite**      | ✔️<br>(Optional)   | ✔️<br>(Optional)   | ✔️<br>(Optional)   | ✔️<br>(Optional)   | ✔️<br>(Optional)   |
| **HiveMind Voice Relay**          | ❌<br>(Unsupported) | 🚧<br>(TODO)       | 🚧<br>(TODO)       | 🚧<br>(TODO)       | ❌<br>(Unsupported) |
| **HiveMind Microphone Satellite** | ❌<br>(Unsupported) | ❌<br>(Unsupported) | ❌<br>(Unsupported) | ❌<br>(Unsupported) | ❌<br>(Unsupported) |

**Other**:

| Supported Plugins                 | **G2P**<br>(mouth movements) | **PHAL**         |
|-----------------------------------|------------------------------|------------------|
| **HiveMind Voice Satellite**      | ✔️<br>(Optional)             | ✔️<br>(Optional) |
| **HiveMind Voice Relay**          | ❌<br>(Unsupported)           | ✔️<br>(Optional) |
| **HiveMind Microphone Satellite** | ❌<br>(Unsupported)           | ✔️<br>(Optional) |

</details>

### Server side plugins

The tables below illustrates how plugins from the OVOS ecosystem relate to the various server setups and where they should
be installed and configured

<details>
  <summary>Click for more details</summary>

**Audio input**:

| Supported Plugins           | **Microphone**     | **VAD**            | **Wake Word**      | **STT**            |
|-----------------------------|--------------------|--------------------|--------------------|--------------------|
| **Hivemind Skills Server**  | ❌<br>(Unsupported) | ❌<br>(Unsupported) | ❌<br>(Unsupported) | ❌<br>(Unsupported) | 
| **Hivemind Sound Server**   | ❌<br>(Unsupported) | ✔️<br>(Required)   | ✔️<br>(Required)   | ✔️<br>(Required)   | 
| **Hivemind Persona Server** | ❌<br>(Unsupported) | ❌<br>(Unsupported) | ❌<br>(Unsupported) | ❌<br>(Unsupported) | 

**Audio output**:

| Supported Plugins           | **TTS**            | **Media Playback** | **OCP extractors** | 
|-----------------------------|--------------------|--------------------|--------------------| 
| **Hivemind Skills Server**  | ❌<br>(Unsupported) | ❌<br>(Unsupported) | ✔️<br>(Optional)   |  
| **Hivemind Sound Server**   | ✔️<br>(Required)   | ❌<br>(Unsupported) | ✔️<br>(Optional)   | 
| **Hivemind Persona Server** | ❌<br>(Unsupported) | ❌<br>(Unsupported) | ❌<br>(Unsupported) |  

**Transformers**:

| Supported Plugins           | **Audio**          | **Utterance**      | **Metadata**       | **Dialog**         | **TTS**            |
|-----------------------------|--------------------|--------------------|--------------------|--------------------|--------------------|
| **Hivemind Skills Server**  | ❌<br>(Unsupported) | ❌<br>(Unsupported) | ❌<br>(Unsupported) | ❌<br>(Unsupported) | ❌<br>(Unsupported) |
| **Hivemind Sound Server**   | 🚧<br>(TODO)       | ✔️<br>(Optional)   | ✔️<br>(Optional)   | ✔️<br>(Optional)   | 🚧<br>(TODO)       |
| **Hivemind Persona Server** | ❌<br>(Unsupported) | 🚧<br>(TODO)       | ❌<br>(Unsupported) | 🚧<br>(TODO)       | ❌<br>(Unsupported) |

**Other**:

| Supported Plugins           | **G2P**<br>(mouth movements) | **PHAL**           |
|-----------------------------|------------------------------|--------------------|
| **Hivemind Skills Server**  | ❌<br>(Unsupported)           | ❌<br>(Unsupported) |
| **Hivemind Sound Server**   | ❌<br>(Unsupported)           | ❌<br>(Unsupported) |
| **Hivemind Persona Server** | ❌<br>(Unsupported)           | ❌<br>(Unsupported) |

</details>

---

## 🔒 Protocol Support

| Feature              | Protocol v0 | Protocol v1 |
|----------------------|-------------|-------------|
| JSON serialization   | ✅           | ✅           |
| Binary serialization | ❌           | ✅           |
| Pre-shared AES key   | ✅           | ✅           |
| Password handshake   | ❌           | ✅           |
| PGP handshake        | ❌           | ✅           |
| Zlib compression     | ❌           | ✅           |

> **Note**: Some clients (e.g., HiveMind-JS) do not yet support Protocol v1.

---

## 🤝 Contributing

HiveMind Core is open source and welcomes contributions from the community. If you’d like to contribute, here’s how you can get started:

1. **Fork the Repository**:  
   Fork the [HiveMind Core GitHub repository](https://github.com/JarbasHiveMind/HiveMind-core).

2. **Open an Issue**:  
   Report bugs or suggest features by [creating an issue](https://github.com/JarbasHiveMind/HiveMind-core/issues).

3. **Submit Pull Requests**:  
   Develop your features or bug fixes in a feature branch and submit a pull request to the main repository.

4. **Join the Discussion**:  
   Participate in the [Matrix chat](https://matrix.to/#/#jarbashivemind:matrix.org) to share ideas and collaborate with the community.

---

## ⚖️ License

HiveMind is open-source software, licensed under the [Apache 2.0 License](LICENSE).





