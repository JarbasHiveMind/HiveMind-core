# Getting Started

## Prerequisites

- Python 3.10+
- A running OVOS instance on `localhost:8181` (default agent backend), **or** a
  [Persona](https://github.com/OpenVoiceOS/ovos-persona) server if you want an LLM backend.
- Satellite devices or clients that will connect (e.g. `hivemind-voice-sat`,
  `hivemind-websocket-client`, or the web chat).

---

## Install

```bash
pip install hivemind-core
```

This installs the HiveMind Core server and the `hivemind-core` CLI. The default transport (WebSocket)
and the default database backend (SQLite) are pulled in automatically.

---

## Start the Server

```bash
hivemind-core listen
```

The server starts every network protocol plugin listed in `network_protocol` that is
installed. With both default plugins present it listens on `0.0.0.0:5678` (WebSocket) and
`0.0.0.0:5679` (HTTP), and connects to the OVOS bus at `127.0.0.1:8181`.

---

## Register a Satellite

Before a device can connect it needs credentials. Add them with:

```bash
hivemind-core add-client --name "my-satellite"
```

Example output:

```
Node ID: 1
Friendly Name: my-satellite
Access Key: 42caf3d2405075fb9e7a4e1ff44e4c4f
Password: 5ae486f7f1c26bd4645bd052e4af3ea3
```

Provide the **Access Key** and **Password** to the satellite device's configuration.

---

## Grant Message Types

New clients have an empty `allowed_types` whitelist. The server denies every message, and
every binary payload, until you grant access. For a typical voice satellite:

```bash
hivemind-core allow-msg "recognizer_loop:utterance" 1
hivemind-core allow-msg "speak" 1
```

The second argument is the client ID printed by `add-client`. If you omit it you will be
prompted interactively.

---

## Verify the Connection

```bash
hivemind-core list-clients
```

Once the satellite connects, its `last_seen` timestamp updates.

---

## Next Steps

- [Architecture](architecture.md): understand how messages flow through the server.
- [Configuration](configuration.md): change ports, switch database backend, add TLS.
- [CLI Reference](cli-reference.md): all available commands.
- [Policy Chain](policy.md): fine-grained per-client admission control.

---
[Home](README.md) · [Architecture →](architecture.md)
