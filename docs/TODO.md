# TODO — hivemind-core

## Known issues / in-code TODOs

- **`HiveMindNodeType.NODE` is a placeholder** — in both the websocket and HTTP protocol plugins, every connecting client is assigned `HiveMindNodeType.NODE`. The actual node type (satellite, agent, sub-hub) is not determined from the handshake. Correct node type classification is a TODO.
- **`ESCALATE` from non-slave nodes is silently ignored** — in `HiveMindPlayerProtocol.handle_send()` and the core protocol, `ESCALATE` messages from non-slave nodes are discarded without any error response to the client.
- **Protocol version 0 has no security** — connecting with `protocol_version=0` bypasses handshake and encryption entirely. This is documented but not locked down by default.

## Missing features

- **No rate limiting** — a connected client can emit unlimited messages per second. Misbehaving or compromised clients can saturate the hub.
- **No graceful shutdown for long-lived STT transcription** — if the hub shuts down while a mic-satellite is streaming audio, in-progress audio chunks are discarded without notification.
- **No per-client connection logging to database** — `last_seen` is stored in the database but only updated explicitly; there is no automatic timestamp update on each message.
- **No `hivemind-core` web dashboard** — there is no built-in UI to view connected clients, their permissions, or message traffic. All management is CLI-only.
- **`hivemind-core add-client --admin` has no audit log** — admin flag changes are not logged.

## Architecture suggestions

- Add a `node_type` negotiation step in the handshake (the client could declare its type)
- Implement a simple rate-limiter at the `handle_message()` level (e.g. max N messages/second per client)
- Add `last_seen` auto-update in `handle_message()`
- Consider exposing a `GET /status` endpoint via the HTTP protocol plugin for health monitoring

## Testing gaps

- No integration test for the full connection → handshake → message → response lifecycle
- Protocol version 0 compatibility (no encryption) is not tested
- Multi-client concurrent connection is not tested
- `handle_invalid_key_connected` and `handle_invalid_protocol_version` paths are not tested

## Completed (2026-03-07)

- ✓ `test/unittests/test_protocol_misc.py` added: HiveMindNodeType enum, ProtocolVersion enum, handle_invalid_key_connected, handle_invalid_protocol_version, handle_new_client/handle_client_disconnected callbacks
- ✓ `AUDIT.md` created: documents all 7 fixed bugs (CRIT-1/2, HIGH-1/2/3, MED-1/2/3) and remaining open items
