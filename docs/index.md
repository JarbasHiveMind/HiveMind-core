Last Edit: Gemini CLI - 2026-03-08 - Motive: Initial compliance with AGENTS.md documentation standards

# HiveMind Core

HiveMind Core is the central hub (master node) of the HiveMind network. It accepts connections from satellites and other nodes, authenticates them, enforces per-client permissions, and routes messages to the configured AI agent backend.

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

- [Architecture Guide](architecture.md) - Deep dive into Mind, Satellite, and Bridge components.
- [Security and Encryption](security.md) - Handshakes, AES-256-GCM, and session keys.
- [Authentication and Client Management](auth.md) - Adding clients and managing permissions.
- [Installation](installation.md) - Getting started with HiveMind Core.
- [Configuration](configuration.md) - Configuring protocols and databases.
- [CLI Reference](cli.md) - Complete command-line reference.
- [Protocol Internals](protocol.md) - Deep dive into the HiveMind message format.
- [Plugin System](plugins.md) - Overview of the modular plugin architecture.
- [Plugin Development](plugin_development.md) - Guide for creating custom plugins.

## License

HiveMind Core v4.0+ is licensed under **AGPL-3.0**. Commercial deployments that cannot comply with AGPL disclosure obligations require a separate commercial license. Contact [jarbasai@mailfence.com](mailto:jarbasai@mailfence.com).

The last Apache-2.0 release was `hivemind-core` **3.4.0**.
