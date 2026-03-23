
# hivemind-core — Quick Facts

> Machine-readable reference for `hivemind-core`.

---

## Package Details
- **Package Name**: `hivemind-core`
- **Version**: `3.4.1a1`
- **License**: `AGPL-3.0`
- **Entry Points**: `hivemind-core` (CLI)

---

## Key Classes
| Class / Function | File | Description |
|---|---|---|
| `ClientDatabase` | `database.py` | Facade for client management and permission persistence. |
| `HiveMindService` | `service.py` | Main service wrapper for the HiveMind hub. |
| `HiveMindListenerProtocol` | `protocol.py` | Base protocol for handling incoming node connections. Holds `hive_mapper: HiveMapper`. |
| `HiveMindClientConnection` | `protocol.py` | Represents an active client connection. |
| `HiveMapper` | `hive_map.py` | Collects PONG replies and builds a directed graph of reachable nodes. |
| `NodeInfo` | `hive_map.py` | Dataclass: `peer`, `site_id`, `pong_timestamp`, `ping_timestamp`, `rtt_ms` property. |
| `handle_ping_message()` | `protocol.py` | Sends PONG back to client; emits `hive.ping.received` on agent bus. |
| `handle_pong_message()` | `protocol.py` | Feeds PONG into `hive_mapper`; emits `hive.pong.received` on agent bus. |

## Node Roles
| Role | Definition |
|---|---|
| **Master** | Any node running `HiveMindListenerProtocol`. Accepts inbound satellite connections. |
| **Satellite** | Any node connected to a master via `HiveMindSlaveProtocol`. |
| **Relay** | A node that is simultaneously a satellite (upstream) and a master (downstream), sharing one AI agent bus. |

Roles are **not mutually exclusive** — a relay node is both master and satellite.

---

## Configuration
- Default config: `~/.config/hivemind-core/server.json`
- Default Port (WebSocket): `5678`
- Default Port (HTTP): `5679`

## Admin API — Database Profile Endpoints
| Endpoint | Method | Description |
|---|---|---|
| `/database/profiles` | GET | List profiles + active name (by comparison) |
| `/database/profiles` | POST | Create a new profile |
| `/database/profiles/{name}` | GET | Get single profile |
| `/database/profiles/{name}` | PUT | Update profile |
| `/database/profiles/{name}` | DELETE | Delete profile |
| `/database/profiles/{name}/activate` | POST | Activate + optional migrate |
| `/database/profiles/{name}/test` | POST | Test connectivity |
| `/database/backends` | GET | List installed DB plugins |

## Admin API — Persona Endpoints
| Endpoint | Method | Description |
|---|---|---|
| `/personas` | GET | List all personas |
| `/personas` | POST | Create persona |
| `/personas/{name}` | GET | Get single persona |
| `/personas/{name}` | PUT | Update persona |
| `/personas/{name}` | DELETE | Delete persona |
| `/plugins/solvers` | GET | List installed solver plugins |

## Frontend Test Suite
- **Location**: `test/frontend/`
- **Runner**: Jest 29 + jsdom
- **Tests**: 67 passing (database profiles UI)
- **Run**: `cd test/frontend && npm test`
