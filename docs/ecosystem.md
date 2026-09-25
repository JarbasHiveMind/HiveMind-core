# HiveMind Ecosystem

This page maps every repository in the HiveMind ecosystem to its role and links to its own documentation.

---

## Core infrastructure

| Repo | Role | Docs |
|---|---|---|
| **hivemind-core** | Central server. Authenticates clients, routes messages, enforces permissions | [docs](index.md) |
| **hivemind-plugin-manager** | Plugin discovery and factory system used by hivemind-core | [repo](https://github.com/JarbasHiveMind/hivemind-plugin-manager) |
| **hivemind-websocket-client** | Python client library and CLI for connecting to a HiveMind Core server | [docs](https://github.com/JarbasHiveMind/hivemind-websocket-client/blob/dev/docs/index.md) |
| **poorman_handshake** | RSA + password-based handshake primitives used for key exchange | [repo](https://github.com/JarbasHiveMind/poorman_handshake) |
| **z85base91** | Binary-to-text encoding schemes (Z85B, Z85P, Base91) used for wire efficiency | [repo](https://github.com/JarbasHiveMind/z85base91) |
| **HiveBeacon** | UDP LAN broadcast and discovery. Advertises the server's presence on the local network | [repo](https://github.com/JarbasHiveMind/HiveBeacon) |

---

## Network protocol plugins

Transport layer plugins loaded by hivemind-core. Multiple can run simultaneously.

| Repo | Entry-point name | Docs |
|---|---|---|
| **hivemind-websocket-protocol** | `hivemind-websocket-plugin` | [docs](https://github.com/JarbasHiveMind/hivemind-websocket-protocol/blob/dev/docs/index.md) |
| **hivemind-http-protocol** | `hivemind-http-plugin` | [repo](https://github.com/JarbasHiveMind/hivemind-http-protocol) |

---

## Binary protocol plugins

Handle binary payloads (audio, images, files) arriving at the server.

| Repo | Entry-point name | Docs |
|---|---|---|
| **hivemind-audio-binary-protocol** | `hivemind-audio-binary-protocol-plugin` | [repo](https://github.com/JarbasHiveMind/hivemind-audio-binary-protocol) |

---

## Database plugins

Credential storage backends.

| Repo | Entry-point name | Docs |
|---|---|---|
| **hivemind-json-db-plugin** | `hivemind-json-db-plugin` | (bundled with json_database) |
| **hivemind-sqlite-database** | `hivemind-sqlite-db-plugin` | [repo](https://github.com/JarbasHiveMind/hivemind-sqlite-database) |
| **hivemind-redis-database** | `hivemind-redis-db-plugin` | [repo](https://github.com/JarbasHiveMind/hivemind-redis-database) |

---

## Satellite clients

Devices that connect to a HiveMind Core server and provide voice or chat interaction.

| Repo | Processing model | Requires audio binary protocol | Docs |
|---|---|---|---|
| **HiveMind-voice-sat** | Wake word, STT, and TTS all run **on device** | No | [docs](https://github.com/JarbasHiveMind/HiveMind-voice-sat/blob/dev/docs/index.md) |
| **HiveMind-voice-relay** | Wake word on device. STT and TTS offloaded **to the server** | Yes | [docs](https://github.com/JarbasHiveMind/HiveMind-voice-relay/blob/dev/docs/index.md) |
| **hivemind-mic-satellite** | Only mic and VAD on device. All audio streamed **to the server** | Yes | [docs](https://github.com/JarbasHiveMind/hivemind-mic-satellite/blob/dev/docs/index.md) |
| **hivemind-webspeech** | VAD in the browser. Audio streamed to the server through JS | Yes | [docs](https://github.com/JarbasHiveMind/hivemind-webspeech/blob/dev/docs/index.md) |

---

## Bridges

Connect external messaging platforms to a HiveMind Core server.

| Repo | Platform | Docs |
|---|---|---|
| **hivemind-flask-chatroom** | Web browser (Flask multi-user chatroom) | [repo](https://github.com/JarbasHiveMind/hivemind-flask-chatroom) |
| **HiveMind-matrix-bridge** | Matrix chat protocol | [repo](https://github.com/JarbasHiveMind/HiveMind-matrix-bridge) |
| **HiveMind-deltachat-bridge** | DeltaChat (email-based) | [repo](https://github.com/JarbasHiveMind/HiveMind-deltachat-bridge) |

---

## OVOS-side plugins

Plugins that run inside an OpenVoiceOS instance and connect it outward to a HiveMind Core server.

| Repo | Type | Purpose | Docs |
|---|---|---|---|
| **ovos-hivemind-pipeline-plugin** | OVOS intent pipeline plugin | Forward unmatched utterances to a remote HiveMind Core server | [repo](https://github.com/JarbasHiveMind/ovos-hivemind-pipeline-plugin) |
| **ovos-solver-hivemind-plugin** | OVOS solver plugin | Query a HiveMind Core server as a question-answering backend | [repo](https://github.com/JarbasHiveMind/ovos-solver-hivemind-plugin) |

---

## Specialised applications

| Repo | Description | Docs |
|---|---|---|
| **hivemind-media-player** | Turn any device into an OCP (OVOS Common Play) media player controlled via HiveMind | [repo](https://github.com/JarbasHiveMind/hivemind-media-player) |
| **hivemind-homeassistant** | Home Assistant custom integration. Exposes HiveMind devices as HA media players | [docs](https://github.com/JarbasHiveMind/hivemind-homeassistant/blob/dev/docs/index.md) |
| **hivemind-ggwave** | Data-over-sound pairing. Provisions satellite credentials over audio, without a keyboard | [docs](https://github.com/JarbasHiveMind/hivemind-ggwave/blob/dev/docs/index.md) |

---

## Docker / deployment

| Repo | Description | Docs |
|---|---|---|
| **hivemind-docker** | Docker Compose stacks for running various HiveMind services | [repo](https://github.com/JarbasHiveMind/hivemind-docker) |
| **hivemind-skills-server-docker** | Docker setup for a persona-based HiveMind skills server | [docs](https://github.com/JarbasHiveMind/hivemind-skills-server-docker/blob/master/docs/index.md) |

---
[← Network Map](hive_map.md) · [Home](index.md)
