# HiveMind Ecosystem

This page maps every repository in the HiveMind ecosystem to its role and links to its own documentation.

---

## Core infrastructure

| Repo | Role | Docs |
|---|---|---|
| **hivemind-core** | Hub server — authenticates clients, routes messages, enforces permissions | [docs](index.md) |
| **hivemind-plugin-manager** | Plugin discovery and factory system used by hivemind-core | [docs](../../hivemind-plugin-manager/docs/index.md) |
| **hivemind-websocket-client** | Python client library and CLI for connecting to a hub | [docs](../../hivemind-websocket-client/docs/index.md) |
| **poorman_handshake** | RSA + password-based handshake primitives used for key exchange | [docs](../../poorman_handshake/docs/index.md) |
| **z85base91** | Binary-to-text encoding schemes (Z85B, Z85P, Base91) used for wire efficiency | [docs](../../z85base91/docs/index.md) |
| **HiveBeacon** | UDP LAN broadcast / discovery — advertises hub presence on the local network | [docs](../../HiveBeacon/docs/index.md) |

---

## Network protocol plugins

Transport layer plugins loaded by hivemind-core. Multiple can run simultaneously.

| Repo | Entry-point name | Docs |
|---|---|---|
| **hivemind-websocket-protocol** | `hivemind-websocket-plugin` | [docs](../../hivemind-websocket-protocol/docs/index.md) |
| **hivemind-http-protocol** | `hivemind-http-plugin` | [docs](../../hivemind-http-protocol/docs/index.md) |

---

## Binary protocol plugins

Handle binary payloads (audio, images, files) arriving at the hub.

| Repo | Entry-point name | Docs |
|---|---|---|
| **hivemind-audio-binary-protocol** | `hivemind-audio-binary-protocol-plugin` | [docs](../../hivemind-audio-binary-protocol/docs/index.md) |

---

## Database plugins

Credential storage backends.

| Repo | Entry-point name | Docs |
|---|---|---|
| **hivemind-json-db-plugin** | `hivemind-json-db-plugin` | (bundled with json_database) |
| **hivemind-sqlite-database** | `hivemind-sqlite-db-plugin` | [docs](../../hivemind-sqlite-database/docs/index.md) |
| **hivemind-redis-database** | `hivemind-redis-db-plugin` | [docs](../../hivemind-redis-database/docs/index.md) |

---

## Satellite clients

Devices that connect to a hub and provide voice or chat interaction.

| Repo | Processing model | Requires audio binary protocol | Docs |
|---|---|---|---|
| **HiveMind-voice-sat** | Wake word + STT + TTS all run **on device** | No | [docs](../../HiveMind-voice-sat/docs/index.md) |
| **HiveMind-voice-relay** | Wake word on device; STT + TTS offloaded **to hub** | Yes | [docs](../../HiveMind-voice-relay/docs/index.md) |
| **hivemind-mic-satellite** | Only mic + VAD on device; all audio streamed **to hub** | Yes | [docs](../../hivemind-mic-satellite/docs/index.md) |
| **hivemind-webspeech** | VAD in browser; audio streamed to hub via JS | Yes | [docs](../../hivemind-webspeech/docs/index.md) |

---

## Bridges

Connect external messaging platforms to a HiveMind hub.

| Repo | Platform | Docs |
|---|---|---|
| **hivemind-flask-chatroom** | Web browser (Flask multi-user chatroom) | [docs](../../hivemind-flask-chatroom/docs/index.md) |
| **HiveMind-matrix-bridge** | Matrix chat protocol | [docs](../../HiveMind-matrix-bridge/docs/index.md) |
| **HiveMind-deltachat-bridge** | DeltaChat (email-based) | [docs](../../HiveMind-deltachat-bridge/docs/index.md) |

---

## OVOS-side plugins

Plugins that run inside an OpenVoiceOS instance and connect it outward to a HiveMind hub.

| Repo | Type | Purpose | Docs |
|---|---|---|---|
| **ovos-hivemind-pipeline-plugin** | OVOS intent pipeline plugin | Forward unmatched utterances to a remote HiveMind hub | [docs](../../ovos-hivemind-pipeline-plugin/docs/index.md) |
| **ovos-solver-hivemind-plugin** | OVOS solver plugin | Query a HiveMind hub as a question-answering backend | [docs](../../ovos-solver-hivemind-plugin/docs/index.md) |

---

## Specialised applications

| Repo | Description | Docs |
|---|---|---|
| **hivemind-media-player** | Turn any device into an OCP (OVOS Common Play) media player controlled via HiveMind | [docs](../../hivemind-media-player/docs/index.md) |
| **hivemind-homeassistant** | Home Assistant custom integration — exposes HiveMind devices as HA media players | [docs](../../hivemind-homeassistant/docs/index.md) |
| **hivemind-ggwave** | Data-over-sound pairing — provision satellite credentials via audio without a keyboard | [docs](../../hivemind-ggwave/docs/index.md) |

---

## Docker / deployment

| Repo | Description | Docs |
|---|---|---|
| **hivemind-docker** | Docker Compose stacks for running various HiveMind services | [docs](../../hivemind-docker/docs/index.md) |
| **hivemind-skills-server-docker** | Docker setup for a persona-based HiveMind skills server | [docs](../../hivemind-skills-server-docker/docs/index.md) |
