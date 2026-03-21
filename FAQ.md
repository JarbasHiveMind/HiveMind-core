# FAQ — HiveMind Core

## What is HiveMind Core?
Central hub of the HiveMind mesh network. Runs `HiveMindListenerProtocol` to accept satellite connections, route messages, and bridge to an AI agent (OVOS or any `AgentProtocol` plugin).

## How do I connect a satellite?
1. `hivemind-core add-client` → generates Access Key + Password
2. Configure key/password on the satellite
3. Satellite connects via WebSocket (default port 5678) or HTTP (5679)

## What is the difference between payload and transport messages?
**Payload messages** (BUS, SHARED_BUS, INTERCOM, BINARY) are consumed at the receiving node — never forwarded by the protocol.
**Transport messages** (PROPAGATE, BROADCAST, ESCALATE) always do two things: unpack + handle the inner payload AND forward the outer wrapper. These operations are independent — inner handling never short-circuits forwarding.
See: `docs/protocol.md` §2

## What is a relay node?
A node that is simultaneously a master (accepting downstream satellites) and a satellite (connected upstream to another master). Both sides share the same agent and bus. Relay is native to hivemind-core via `HiveMindListenerProtocol.upstream` — `protocol.py:235`.

## How does native relay work?
Set `master_protocol.upstream = satellite.send`. PROPAGATE and ESCALATE from downstream are automatically forwarded upstream. For downstream BROADCAST/PROPAGATE from upstream, wire `satellite.on(BROADCAST, master_protocol.handle_upstream_message)`.
See: `docs/protocol.md` §4

## Do BUS messages travel through relays?
No. BUS is consumed-only — it's injected into the immediate master's agent bus and stops there. If the relay's agent (e.g., OVOS pipeline plugin) decides to escalate unhandled utterances upstream, that's an agent-level decision, not protocol behavior.
See: `docs/protocol.md` §4.5

## What happens if a satellite sends an unauthorized message?
- Non-admin sends BROADCAST → `client.disconnect()` — `protocol.py:637`
- `can_propagate=False` sends PROPAGATE → `client.disconnect()` — `protocol.py:683`
- `can_escalate=False` sends ESCALATE → `client.disconnect()` — `protocol.py:803`
- Unauthorized BUS message type → silently dropped — `protocol.py:921-923`

## Is communication encrypted?
Yes. After handshake, all messages are encrypted. Supports AES-GCM (default) and CHACHA20-POLY1305 ciphers with multiple encoding options (B64, B91, Z85, HEX, B32).
Source: `HiveMindClientConnection.send` — `protocol.py:120`

## Can I restrict what a satellite can do?
Yes, per-client permissions: `is_admin`, `can_propagate`, `can_escalate`, `allowed_types` (BUS whitelist), `msg_blacklist`, `skill_blacklist`, `intent_blacklist`.
Source: `HiveMindClientConnection` — `protocol.py:72-107`

## What is hive.send.upstream?
A bus event emitted when `HiveMindListenerProtocol.upstream` is NOT set (legacy mode). `HiveMindSlaveInternalProtocol` picks it up and forwards upstream. With native relay (`upstream` set), this event is NOT emitted — the callable is used directly. Agent plugins can still emit `hive.send.upstream` to initiate HiveMind messages.
See: `_send_upstream` — `protocol.py:952`

## What database backends are supported?
Pluggable via `ClientDatabase`. Options: JSON (default), SQLite, Redis.
Source: `ClientDatabase` — `database.py`

## Where is the configuration stored?
`~/.config/hivemind-core/server.json`
Source: `get_server_config` — `config.py`
