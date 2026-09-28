# HiveMind Core — Documentation

HiveMind Core is the central server for the HiveMind network. It accepts authenticated,
encrypted connections from satellite devices and AI agents, routes HiveMessages between
them and the agent backend, and enforces per-client permissions through a configurable
policy chain.

---

## Contents

| Document | Purpose |
|---|---|
| [getting-started.md](getting-started.md) | Install, first satellite, run the server |
| [architecture.md](architecture.md) | How the server works end-to-end: message flow, protocol layers, plugin types |
| [configuration.md](configuration.md) | Full `server.json` reference, all keys and defaults |
| [cli-reference.md](cli-reference.md) | Every `hivemind-core` subcommand with examples |
| [policy.md](policy.md) | Policy admission chain: how it works, authoring plugins, deny codes |
| [plugins.md](plugins.md) | How to wire a database, network, agent, or binary plugin |
| [extending.md](extending.md) | Writing custom database, network, agent, and policy plugins |

---

## Quick Links

- **GitHub**: [JarbasHiveMind/HiveMind-core](https://github.com/JarbasHiveMind/HiveMind-core)
- **Community docs**: [jarbashivemind.github.io/HiveMind-community-docs](https://jarbashivemind.github.io/HiveMind-community-docs)
- **Plugin manager ABCs**: [hivemind-plugin-manager](https://github.com/JarbasHiveMind/hivemind-plugin-manager)
- **Matrix chat**: [#jarbashivemind:matrix.org](https://matrix.to/#/#jarbashivemind:matrix.org)
