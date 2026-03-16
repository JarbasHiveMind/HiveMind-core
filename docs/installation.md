# Installation

## Requirements

- Python 3.8+
- At least one network protocol plugin (e.g. `hivemind-websocket-protocol`)
- At least one agent protocol plugin (e.g. `hivemind-ovos-agent-plugin`)

## Install from PyPI

```bash
pip install hivemind-core
```

## Install with optional database backends

```bash
# SQLite backend
pip install hivemind-core hivemind-sqlite-database

# Redis backend
pip install hivemind-core hivemind-redis-database
```

The default database backend is JSON (`hivemind-json-db-plugin`), which is installed automatically as a dependency.

## Install network protocol plugins

```bash
# WebSocket support
pip install hivemind-websocket-protocol

# HTTP support
pip install hivemind-http-protocol
```

## Install agent protocol plugins

```bash
# OpenVoiceOS integration
pip install hivemind-ovos-agent-plugin

# LLM / Persona integration
pip install ovos-persona
```

## Verify installation

```bash
hivemind-core --help
```

## Next step

After installing, [configure the server](configuration.md) and [add your first client](cli.md#add-client).
