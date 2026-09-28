# Installation

## Requirements

- Python 3.10+
- At least one network protocol plugin (e.g. `hivemind-websocket-protocol`)
- At least one agent protocol plugin (e.g. `hivemind-ovos-agent-plugin`)

## Install from PyPI

```bash
pip install --pre hivemind-core
```

hivemind-core is published as pre-releases, so pass `--pre`. Without it, pip installs
the last stable release, 4.0.0, and its dependencies. That release predates the
protocol v3 (Noise) handshake these docs describe and lacks commands such as
`reset-noise-pin` and `derive-psk`. With uv, the same install is
`uv pip install --prerelease=allow hivemind-core`.

## Install with optional database backends

```bash
# Redis backend
pip install --pre hivemind-core hivemind-redis-database
```

Fresh installs use the SQLite backend (`hivemind-sqlite-database`) by default. It installs automatically as a dependency, along with the JSON backend (`hivemind-json-db-plugin`) for existing JSON deployments.

## Install network protocol plugins

```bash
# WebSocket support
pip install --pre hivemind-websocket-protocol

# HTTP support
pip install --pre hivemind-http-protocol
```

## Install agent protocol plugins

```bash
# OpenVoiceOS integration
pip install --pre hivemind-ovos-agent-plugin

# LLM / Persona integration
pip install --pre ovos-persona
```

## Several nodes on one machine

A node keeps its state in XDG directories: `server.json` and the node identity
under `$XDG_CONFIG_HOME` (`hivemind-core/server.json`, `hivemind/_identity.json`),
and the client database under `$XDG_DATA_HOME/hivemind-core`. Two nodes that share
these directories share one configuration, one identity and one client list.

To run a second node on the same machine, give it its own directories and its own
ports:

```bash
XDG_CONFIG_HOME=$HOME/node2/config XDG_DATA_HOME=$HOME/node2/data hivemind-core listen
```

In that node's `server.json`, set a free port for each transport in
`network_protocol`. If a port is already taken, the transport logs
`OSError: [Errno 98] Address already in use`. When no transport is left, the node
logs `Every network protocol has stopped, this node no longer accepts clients`.

The `agent_protocol` port selects the OVOS messagebus the node talks to. Two nodes
with the same port there use the same OVOS instance. Give each node its own port
if each needs its own OVOS.

## Verify installation

```bash
hivemind-core --help
```

## Next step

After installing, [configure the server](configuration.md) and [add your first client](cli.md#add-client).

---
[← Authentication](auth.md) · [Home](index.md) · [Security →](security.md)
