# Maintenance Report - HiveMind Core

## 2026-03-23 — QUERY/CASCADE/PING/INTERCOM handler rewrite (feat/query-cascade-v2)

- **AI Model**: claude-sonnet-4-6
- **Actions Taken**:
  - Rewrote `handle_query_message`: async callback + `threading.Timer` escalation via `AgentProtocol.handle_query(msg, callback, timeout)`; removed metadata/query_id machinery
  - Rewrote `handle_cascade_message`: inject locally + flood all peers; removed `CascadeResponse`/`CascadeCollector`; aggregation delegated to client-side `CascadeAggregator`
  - Rewrote `handle_ping_message`: uses `HiveMapper.check_flood_id()` (replaces `_seen_flood_ids`); adds `public_key`/`lang` to responsive PING
  - Rewrote `handle_intercom_message`: uses `hybrid_decrypt` (RSA+AES-GCM) instead of raw `decrypt_RSA`; trust gate via `identity.is_trusted_key()`
  - Simplified `query_to_master`/`cascade_to_master`: removed metadata param
  - Removed: pybase64 dependency, dead code classes `CascadeResponse`/`CascadeCollector`
  - Fixed broken test imports in test_bus.py/test_db.py/test_hive_map.py (previous agent invented nonexistent classes)
  - Added 17 new protocol handler tests; 59 total tests passing
- **Oversight**: Human reviewed plan, approved architectural decisions (async callback pattern, no metadata, client-side aggregation)

## Current State
HiveMind Core is in a stable state, with version 4.0 introducing AGPL-3.0 licensing and advanced modular features. The project follows a plugin-based architecture for network protocols, agent protocols, binary data handling, and databases.

## Key Modules
- `hivemind_core.protocol`: Contains the core HiveMind protocol logic (`HiveMindListenerProtocol`) and client connection handling (`HiveMindClientConnection`). This is the most active and critical part of the codebase.
- `hivemind_core.service`: Manages the service lifecycle (`HiveMindService`), initializing all plugins and starting network listeners.
- `hivemind_core.database`: Provides an abstraction layer for client management, allowing different backends.
- `hivemind_core.config`: Handles XDG-compliant configuration management.

## Health Summary
- **Protocol Reliability**: The protocol handles various message types (`BUS`, `PROPAGATE`, `BROADCAST`, `ESCALATE`, `INTERCOM`, `BINARY`) with built-in validation and authorization checks.
- **Security**: Strong encryption is implemented via `poorman-handshake` and established cryptographic ciphers.
- **Modularity**: Excellent use of plugin factories (`AgentProtocolFactory`, `NetworkProtocolFactory`, etc.) allows easy extension without modifying core code.
- **Dependencies**: Relies on `ovos-bus-client`, `ovos-utils`, and `hivemind-plugin-manager`.

## Maintenance Tasks
- Regular updates to plugin dependencies are recommended.
- Protocol versioning is in place (`ProtocolVersion`), ensuring backward compatibility where possible.
- Documentation should be kept in sync with protocol changes.
Source: `ProtocolVersion` — `hivemind_core/protocol.py:46`
Source: `HiveMindService.run` — `hivemind_core/service.py:167`
