# HiveMind Core

HiveMind Core is the central server of the HiveMind network. It accepts connections from satellites and other nodes, authenticates them, enforces per-client permissions, and routes messages to the configured AI agent backend.

## Overview

```
Satellite / Client
       │
       │  WebSocket / HTTP (encrypted)
       ▼
 ┌─────────────┐
 │ hivemind-   │  Network Protocol Plugin (WebSocket, HTTP, …)
 │    core     │──────────────────────────────────────────────▶ Agent Protocol Plugin (OVOS, Persona, …)
 │             │  Binary Protocol Plugin (audio, image, file)
 └─────────────┘
       │
  ClientDatabase (JSON, SQLite, Redis)
```

HiveMind Core is fully **plugin-driven**:

| Layer | Role | Configured by |
|---|---|---|
| **Network protocol** | How messages are transported (WebSocket, HTTP) | `network_protocol` config key |
| **Agent protocol** | What handles message payloads (OVOS bus, LLM persona) | `agent_protocol` config key |
| **Binary protocol** | What to do with received binary data (audio, images) | `binary_protocol` config key |
| **Database** | Where client credentials are stored (JSON, SQLite, Redis) | `database` config key |

## Documentation

- [Architecture Guide](architecture.md): explains the Mind, Satellite, and Bridge components.
- [Security and Encryption](security.md): covers the Noise handshake, AES-256-GCM, and the encrypted transport.
- [Authentication and Client Management](auth.md): covers adding clients and managing permissions.
- [Installation](installation.md): gets you started with HiveMind Core.
- [Configuration](configuration.md): covers configuring protocols and databases.
- [CLI Reference](cli.md): a complete command-line reference.
- [Protocol Internals](protocol.md): explains the HiveMind message format.
- [Plugin System](plugins.md): an overview of the modular plugin architecture.
- [Transformer Pipelines](transformers.md): OVOS transformer plugins on the text/bus path.
- [Plugin Development](plugin_development.md): a guide for creating custom plugins.

## License

HiveMind-core is licensed under **Apache-2.0**. Releases up to `hivemind-core` **3.4.0** were Apache-2.0. The **4.x** series shipped under AGPL-3.0 as a short-lived experiment. From this release forward, HiveMind-core returns to Apache-2.0. Previously published 3.x and 4.x releases on PyPI stay under the license they were published with. Contact [jarbasai@mailfence.com](mailto:jarbasai@mailfence.com) for support or sponsorship.
