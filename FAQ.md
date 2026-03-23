# FAQ — HiveMind Core

## What is the difference between payload and transport messages?
**Payload messages** (BUS, SHARED_BUS, INTERCOM, BINARY) are consumed at the receiving node — never forwarded by the protocol.
**Transport messages** (PROPAGATE, BROADCAST, ESCALATE) always do two things: unpack + handle the inner payload AND forward the outer wrapper. These operations are independent — inner handling never short-circuits forwarding.
See: `docs/protocol.md` §2

## What is a relay node?
A node that is simultaneously a master (accepting downstream satellites) and a satellite (connected upstream to another master). Both sides share the same agent bus. A relay is just `HiveMindListenerProtocol` + `HiveMindSlaveProtocol` bound to the same bus — no special configuration needed.

## How does relay work?
Both protocol sides share the same bus. `_send_upstream()` emits `hive.send.upstream` on the bus, which `HiveMindSlaveInternalProtocol.handle_send()` picks up and forwards upstream. `HiveMindSlaveProtocol.handle_broadcast/propagate()` emits `hive.send.downstream`, which the agent protocol routes to downstream clients.
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

## How does PING-based network discovery work?
A master sends `PROPAGATE(PING)` with a unique `flood_id`. Each node that receives it records the sender in its `HiveMapper`, then builds and sends its own responsive PING (same `flood_id`) to all peers. The `flood_id` prevents infinite loops — each node only responds once per `flood_id`.
Source: `HiveMapper.on_ping` — `hive_map.py:59`, `handle_ping_message` — `protocol.py:713`

## What is `flood_id`?
A UUID string included in every PING payload. It identifies a single discovery session. Each node tracks seen `flood_id` values via `HiveMapper.check_flood_id()`, which uses an `OrderedDict` FIFO eviction capped at 10,000 entries.
Source: `HiveMapper.check_flood_id` — `hivemind_bus_client/hive_map.py`, `handle_ping_message` — `protocol.py`

## How does HiveMapper build the topology graph?
`HiveMapper` collects responsive PINGs and extracts two things: (1) `NodeInfo` (peer, site_id, timestamps) from the PING payload, and (2) directed edges from the `route` field on the outer PROPAGATE wrapper. Each hop in the route records `{source, targets}`. The union of all routes forms the complete hive topology.
Source: `HiveMapper` — `hive_map.py:31`

## How do relays handle flood_id deduplication?
Relay nodes share the `HiveMapper` instance between their master and satellite sides. `HiveMapper.check_flood_id()` returns `True` if already seen (FIFO eviction), preventing re-propagation on the other side.
Source: `HiveMapper.check_flood_id` — `hivemind_bus_client/hive_map.py`

## Where is the configuration stored?
`~/.config/hivemind-core/server.json`
Source: `get_server_config` — `config.py`

## How does QUERY work?
QUERY = "first answering node wins, else escalate". The server calls `agent_protocol.handle_query(bus_msg, callback, timeout)`. If the agent calls `callback(response)` within `timeout` seconds, a `QUERY(BUS)` response is sent back to the client. Otherwise `query_to_master(payload)` escalates upstream. Direction is implicit — no `query_id`/`is_response` metadata needed.
Source: `handle_query_message` — `protocol.py`, `AgentProtocol.handle_query` — `hivemind_plugin_manager/protocols.py`

## How does CASCADE work?
CASCADE = inject locally + flood all peers. The server handles the inner BUS or INTERCOM on the local agent bus, then forwards the CASCADE message to all other connected clients and upstream (if relay). Response aggregation is done client-side by `CascadeAggregator` in `hivemind_bus_client`.
Source: `handle_cascade_message` — `protocol.py`

## How does INTERCOM encryption work?
INTERCOM payloads use hybrid RSA+AES-GCM encryption. The sender encrypts with the target node's public RSA key wrapping an AES-GCM key. The receiver calls `hybrid_decrypt(private_key, payload)`. Unencrypted INTERCOM from trusted peers (verified via `identity.is_trusted_key(peer_pubkey)`) is also accepted.
Source: `handle_intercom_message` — `protocol.py`, `hybrid_decrypt` — `hivemind_bus_client/encryption.py`
