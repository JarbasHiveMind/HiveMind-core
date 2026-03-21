# HiveMind Protocol Specification

Canonical reference for message types, routing rules, and relay architecture.

Source: `HiveMessageType` — `hivemind_bus_client/message.py:9`
Master handler: `HiveMindListenerProtocol` — `hivemind_core/protocol.py:222`
Satellite handler: `HiveMindSlaveProtocol` — `hivemind_bus_client/protocol.py:80`

---

## 1. Message Structure

Every HiveMind communication is a `HiveMessage` (`hivemind_bus_client/message.py:45`).

| Field | Type | Description |
|-------|------|-------------|
| `msg_type` | `HiveMessageType` | Determines routing and handling behavior |
| `payload` | `Message \| HiveMessage \| dict \| bytes` | Content — type depends on `msg_type` |
| `route` | `List[dict]` | Hop trail: `[{"source": peer, "targets": [peers]}]` |
| `source_peer` | `str` | Peer ID of the node that last forwarded this message |
| `target_peers` | `List[str]` | Intended recipients |
| `target_site_id` | `str` | Target site for site-directed delivery |
| `target_pubkey` | `str` | RSA public key for INTERCOM encryption targeting |
| `bin_type` | `HiveMindBinaryPayloadType` | Sub-type for BINARY messages only |
| `metadata` | `dict` | Extra data (sample_rate, file_name, etc.) |

### Payload Type Binding

The `payload` property (`message.py:128-146`) reconstructs typed objects based on `msg_type`:

| msg_type | payload returns | Stored as |
|----------|----------------|-----------|
| BUS, SHARED_BUS | `Message` (OVOS bus message) | dict `{"type", "data", "context"}` |
| PROPAGATE, BROADCAST, CASCADE, ESCALATE | `HiveMessage` (nested) | dict (HiveMessage.as_dict) |
| BINARY | `bytes` | raw bytes |
| All others (PING, INTERCOM, THIRDPRTY, etc.) | `dict` | dict |

---

## 2. Message Categories

HiveMind messages fall into two distinct categories: **payload messages** and **transport messages**.

### 2.1 Payload Messages — Consumed, Never Forwarded

Payload messages are delivered to the receiving node's handler and consumed. They are **never forwarded** by the protocol layer.

| Type | Wire value | Direction | Handler (master) | Handler (satellite) |
|------|-----------|-----------|------------------|---------------------|
| **BUS** | `"bus"` | satellite→master, master→satellite | `handle_bus_message` — `protocol.py:602` | `handle_bus` — `protocol.py:225` |
| **SHARED_BUS** | `"shared_bus"` | satellite→master | `handle_client_shared_bus` — `protocol.py:943` | illegal (logged) |
| **INTERCOM** | `"intercom"` | any→any (RSA-targeted) | `handle_intercom_message` — `protocol.py:820` | `handle_intercom` — `protocol.py:360` |
| **BINARY** | `"bin"` | satellite→master, master→satellite | `handle_binary_message` — `protocol.py:467` | N/A (raw receive) |

#### BUS
Injects an OVOS `Message` into the master's agent bus. The master authorizes the message (`client.authorize()`), applies blacklists, sets session context, and emits on the internal bus. The agent protocol decides what to do (run skills, respond, etc.). BUS messages are **never forwarded** through relays at the protocol level — relay forwarding of utterances is an agent-level concern (e.g., OVOS pipeline plugin).

- **Authorization**: `allowed_types` whitelist; empty = allow all — `HiveMindClientConnection.authorize` — `protocol.py:204`
- **Session enforcement**: non-admin clients cannot use `"default"` session — `protocol.py:612`
- **Blacklists**: `msg_blacklist`, `skill_blacklist`, `intent_blacklist` — `protocol.py:886`
- **Reverse routing**: agent responses flow back via `message.context["destination"]` matching the satellite's peer ID

#### SHARED_BUS
Passive monitoring: the satellite shares its internal bus traffic. The master records it via `shared_bus_callback`. Requires `shared_bus=True` on the satellite connection. Read-only — master does not act on these messages.

#### INTERCOM
End-to-end encrypted peer-to-peer messaging using RSA. Can be nested inside transport messages to reach specific nodes. The outer message carries `target_pubkey` to route to the correct recipient. The inner payload (after decryption) is dispatched to the appropriate handler (BUS, PROPAGATE, etc.).

- **Encryption**: RSA encrypt with target's public key — `protocol.py:830-846`
- **Signature verification**: NOT currently implemented (TODO) — `protocol.py:836-841`
- **Inner dispatch**: after decryption, inner message is re-dispatched by type — `protocol.py:854-883`

#### BINARY
Raw binary data with a `bin_type` sub-type that determines handling:

| bin_type | Value | Handler |
|----------|-------|---------|
| `RAW_AUDIO` | 1 | `handle_microphone_input` |
| `NUMPY_IMAGE` | 2 | `handle_numpy_image` |
| `FILE` | 3 | `handle_receive_file` |
| `STT_AUDIO_TRANSCRIBE` | 4 | `handle_stt_transcribe_request` |
| `STT_AUDIO_HANDLE` | 5 | `handle_stt_handle_request` |
| `TTS_AUDIO` | 6 | `handle_receive_tts` |

Source: `HiveMindBinaryPayloadType` — `message.py:33`, `handle_binary_message` — `protocol.py:467`

### 2.2 Transport Messages — Unpack + Handle + Forward

Transport messages define **routing behavior**. Every transport message performs two independent operations:

1. **Unpack**: extract the inner payload and dispatch it to the appropriate handler
2. **Forward**: re-wrap and send the outer message to the correct destinations

**These operations are independent.** Inner payload handling NEVER short-circuits forwarding. Even if the inner INTERCOM is successfully decrypted and handled locally, the outer transport message is still forwarded to all appropriate destinations.

| Type | Wire value | Forward direction | Permission | Handler |
|------|-----------|-------------------|------------|---------|
| **BROADCAST** | `"broadcast"` | All downstream slaves | `is_admin` required | `handle_broadcast_message` — `protocol.py:625` |
| **PROPAGATE** | `"propagate"` | All peer slaves + upstream masters | `can_propagate` required | `handle_propagate_message` — `protocol.py:667` |
| **ESCALATE** | `"escalate"` | Upstream masters only | `can_escalate` required | `handle_escalate_message` — `protocol.py:785` |

#### BROADCAST
Admin-only. Forwards to all connected slaves except the sender. The inner payload is unpacked and handled locally (INTERCOM dispatch, site-targeted BUS injection), then the full BROADCAST wrapper is forwarded.

```
Satellite (admin) → Master
    Master unpacks inner payload → handles locally
    Master wraps in BROADCAST → sends to ALL other slaves
```

**Illegal action**: non-admin satellite sends BROADCAST → `illegal_callback` fired, `client.disconnect()` — `protocol.py:633-638`

#### PROPAGATE
Forwards in ALL directions: to all peer slaves AND upstream. The inner payload is handled locally first (INTERCOM, site-targeted BUS, PING/PONG), then forwarded.

```
Satellite → Master
    Master unpacks inner payload → handles locally (+ PING flood)
    Master wraps in PROPAGATE → sends to ALL other slaves
    Master sends upstream (native relay or hive.send.upstream bus event)
```

**PING flood**: PROPAGATE is the transport layer for network mapping. `PROPAGATE(PING)` triggers each node to send its own responsive PING (same `flood_id`). PONG is no longer used. — `handle_ping_message` — `protocol.py:713`

**Illegal action**: satellite with `can_propagate=False` sends PROPAGATE → `illegal_callback` fired, `client.disconnect()` — `protocol.py:679-684`

#### ESCALATE
Forwards upstream only — never to peer slaves. Used for authority-chain escalation.

```
Satellite → Master
    Master unpacks inner payload → handles locally
    Master sends upstream (native relay or hive.send.upstream bus event)
    (NOT forwarded to other slaves)
```

**Illegal action**: satellite with `can_escalate=False` sends ESCALATE → `illegal_callback` fired, `client.disconnect()` — `protocol.py:799-804`

#### Transport Message Processing Pipeline

All three transport handlers follow the same pipeline (`_unpack_message` — `protocol.py:658`):

```
1. _unpack_message(message, client)
   → payload = message.payload        # reconstructs inner HiveMessage
   → payload.replace_route(message.route)  # transfer route from outer
   → payload.update_source_peer(self.peer) # stamp this node as source
   → payload.remove_target_peer(client.peer) # remove sender from targets

2. Permission check → disconnect if unauthorized

3. Fire callback (propagate_callback, broadcast_callback, escalate_callback)

4. Handle inner payload (INTERCOM, BUS, PING) — NEVER short-circuits

5. Forward: wrap payload in new HiveMessage(same_type, payload=...)
   → Send to appropriate destinations (slaves, upstream, or both)
```

### 2.3 Other Message Types

| Type | Wire value | Category | Description |
|------|-----------|----------|-------------|
| **HELLO** | `"hello"` | Session | Connection announcement; carries pubkey, peer ID, session, site_id |
| **HANDSHAKE** | `"shake"` | Session | Crypto negotiation (password or RSA) |
| **PING** | `"ping"` | Inner payload | Network mapping flood; always wrapped in PROPAGATE. Each node responds with its own PING (same `flood_id`). PONG removed. |
| **QUERY** | `"query"` | Transport (TODO) | Like ESCALATE but stops at first responder |
| **CASCADE** | `"cascade"` | Transport (TODO) | Like PROPAGATE but expects responses from all nodes |
| **THIRDPRTY** | `"3rdparty"` | Payload | User-defined; arbitrary dict payload |
| **RENDEZVOUS** | `"rendezvous"` | Reserved | For rendezvous-node discovery |

---

## 3. Connection Lifecycle

### 3.1 Handshake Flow

```
Master                          Satellite
  │                                │
  │──── HELLO (pubkey, peer) ─────→│
  │──── HANDSHAKE (params) ───────→│
  │                                │
  │←── HANDSHAKE (envelope) ───────│  (password-based)
  │──── HANDSHAKE (envelope) ─────→│
  │                                │
  │←── HELLO (pubkey, session) ────│  (crypto now active)
  │                                │
  │  client registered in          │
  │  self.clients[peer]            │
```

Source: `handle_new_client` — `protocol.py:258`, `handle_handshake_message` — `protocol.py:501`

### 3.2 Client Permissions

Permissions are per-client, stored in the database and enforced at runtime:

| Permission | Default | Effect |
|-----------|---------|--------|
| `is_admin` | `False` | Required for BROADCAST; admin can use "default" session |
| `can_propagate` | `True` | Required for PROPAGATE; violation → disconnect |
| `can_escalate` | `True` | Required for ESCALATE; violation → disconnect |
| `allowed_types` | `[]` (all) | Whitelist of OVOS message types the client can inject via BUS |
| `msg_blacklist` | `[]` | OVOS message types never sent TO this client |
| `skill_blacklist` | `[]` | Skills blocked for this client's session |
| `intent_blacklist` | `[]` | Specific intents blocked for this client's session |

Source: `HiveMindClientConnection` — `protocol.py:72-107`

---

## 4. Native Relay Architecture

A relay node is simultaneously a master (accepting downstream connections) and a satellite (connected upstream to another master). Both sides share the same agent protocol and bus.

### 4.1 Shared Bus Architecture

A relay is a `HiveMindListenerProtocol` (master side) and a `HiveMindSlaveProtocol` (satellite side) sharing the **same agent bus**. No special wiring is needed — the existing bus event handlers provide full relay behavior:

**Upstream forwarding** (downstream satellite → upstream master):
1. R1_master receives PROPAGATE/ESCALATE from downstream satellite
2. `handle_propagate_message` / `handle_escalate_message` calls `_send_upstream()`
3. `_send_upstream()` emits `hive.send.upstream` on the shared bus (full transport wrapper)
4. `HiveMindSlaveInternalProtocol.handle_send()` (`hivemind_bus_client/protocol.py:33`) picks it up and forwards to the upstream master

**Downstream forwarding** (upstream master → downstream satellites):
1. R1_sat receives BROADCAST/PROPAGATE from the upstream master
2. `HiveMindSlaveProtocol.handle_broadcast/propagate()` (`hivemind_bus_client/protocol.py:242,270`) emits `hive.send.downstream` on the shared bus
3. The agent protocol's `handle_send()` picks it up and routes to `self.clients` (R1_master's downstream satellites)

### 4.2 `_send_upstream()`

Called by `handle_propagate_message` and `handle_escalate_message`. Wraps the inner payload in the transport type and emits on the bus:

```python
upstream_msg = HiveMessage(msg_type, payload=payload)
bus.emit(Message("hive.send.upstream", upstream_msg.as_dict, {
    "destination": "hive",
    "source": self.peer,
    "session": client.sess.serialize(),
}))
```

If no `HiveMindSlaveInternalProtocol` is bound to the bus (i.e., this node is the top-level master), the event is silently ignored.

### 4.3 Relay Configuration

```python
shared_bus = FakeBus()  # or MessageBusClient
master_protocol = HiveMindListenerProtocol(agent_protocol=agent, ...)
slave_protocol = HiveMindSlaveProtocol(hm=client, ...)
slave_protocol.bind(shared_bus)  # registers hive.send.upstream listener
# That's it. Bus events handle upstream/downstream forwarding.
```

### 4.4 Message Flow Through Relays

#### ESCALATE through relay chain
```
S0 ──ESCALATE──→ R1_master (HiveMindListenerProtocol)
                   │ _unpack_message + handle inner payload
                   │ _send_upstream(ESCALATE) → bus: hive.send.upstream
                   ↓
                 R1_sat (HiveMindSlaveInternalProtocol.handle_send)
                   │ Reconstructs HiveMessage(ESCALATE, ...) → sends upstream
                   ↓
                 M0 (HiveMindListenerProtocol)
                   │ handle_escalate_message → process
```

#### PROPAGATE through relay chain
```
S0 ──PROPAGATE──→ R1_master
                   │ _unpack_message + handle inner payload
                   │ Forward PROPAGATE to all OTHER slaves of R1
                   │ _send_upstream(PROPAGATE) → bus: hive.send.upstream
                   ↓
                 R1_sat → reconstructs + sends PROPAGATE upstream
                   ↓
                 M0
                   │ Forward PROPAGATE to all OTHER slaves of M0
                   │ _send_upstream (continues up the chain)
```

#### BROADCAST from M0 through relay
```
M0 ──BROADCAST──→ R1_sat (HiveMindSlaveProtocol.handle_broadcast)
                     │ bus: hive.send.downstream
                     ↓
                   TestAgentProtocol.handle_send (or OVOSProtocol)
                     │ Routes to self.clients
                     ↓
                   R1_master ──BROADCAST──→ S0, S1, S2
```

#### BUS (consumed-only, NOT relayed)
```
S0 ──BUS──→ R1_master
              │ handle_bus_message → inject into R1's agent bus
              │ (STOPS HERE — BUS is never forwarded)
              │
              │ R1's agent (OVOS) processes the utterance.
              │ If OVOS pipeline can't handle it, the pipeline plugin
              │ may choose to escalate upstream — but that's an agent
              │ decision, not a protocol decision.
```

---

## 5. Bus Events

HiveMind emits OVOS bus events for integration with agent plugins:

| Bus event | Emitted when | Data |
|-----------|-------------|------|
| `hive.client.connect` | New client completes handshake | `key`, `session_id` |
| `hive.client.disconnect` | Client disconnects | `key` |
| `hive.client.connection.error` | Invalid key or protocol | `error`, `peer` |
| `hive.send.upstream` | Transport message needs upstream relay (legacy mode) | HiveMessage as dict |
| `hive.send.downstream` | Agent wants to send to specific satellite | `payload`, `peer`, `msg_type` |
| `hive.ping.received` | PROPAGATE(PING) received | `ping_id`, `peer`, `site_id` |
| `hive.ping.received` | PROPAGATE(PING) received | `flood_id`, `peer`, `site_id` |

`hive.send.upstream` is the **legacy** upstream relay mechanism. When `HiveMindListenerProtocol.upstream` is set (native relay mode), this event is NOT emitted — the native callable is used instead. Agent plugins can still emit `hive.send.upstream` to initiate HiveMind messages; `HiveMindSlaveInternalProtocol.handle_send()` will pick them up.

---

## 6. Encryption & Serialization

### Transport Layer
All messages are encrypted after the handshake completes:

| Mode | Condition | Format |
|------|-----------|--------|
| JSON encrypted | `crypto_key` set, not binarized | `encrypt_as_json(message.serialize())` |
| Binary encrypted | `crypto_key` set, binarized or BINARY type | `encrypt_bin(get_bitstring(...).bytes)` |
| Plaintext | No crypto (handshake/hello only) | `message.serialize()` → JSON string |

Source: `HiveMindClientConnection.send` — `protocol.py:120-167`

### Supported Ciphers & Encodings
- **Ciphers**: AES-GCM (default), CHACHA20-POLY1305
- **Encodings**: JSON-HEX, JSON-B64, JSON-URLSAFE-B64, JSON-B91, JSON-Z85B, JSON-Z85P, JSON-B32

Negotiated during handshake; client proposes preferences, server selects from allowed list.

Source: `handle_handshake_message` — `protocol.py:501-569`

---

## 7. Satellite-Side Protocol

`HiveMindSlaveProtocol` (`hivemind_bus_client/protocol.py:80`) handles messages received FROM the master.

### Message Handling (satellite receives)

| Type received | Satellite action |
|--------------|-----------------|
| BUS | Inject into internal OVOS bus (`handle_bus` — `protocol.py:225`) |
| BROADCAST | Handle inner payload + emit `hive.send.downstream` on bus (`handle_broadcast` — `protocol.py:242`) |
| PROPAGATE | Dispatch inner (PING flood, INTERCOM) + emit `hive.send.downstream` (`handle_propagate` — `protocol.py:270`) |
| INTERCOM | Decrypt + dispatch inner message (`handle_intercom` — `protocol.py:360`) |
| ESCALATE, SHARED_BUS | Illegal — logged as warning (`handle_illegal_msg` — `protocol.py:132`) |
| HANDSHAKE | Continue handshake negotiation (`handle_handshake` — `protocol.py:190`) |
| HELLO | Store master's pubkey and node_id (`handle_hello` — `protocol.py:138`) |

### Internal Protocol — `HiveMindSlaveInternalProtocol`

`HiveMindSlaveInternalProtocol` (`hivemind_bus_client/protocol.py:21`) bridges the OVOS bus and the HiveMind connection:

| Bus event | Action |
|-----------|--------|
| `hive.send.upstream` | Reconstruct HiveMessage and send to master (except BROADCAST — silently ignored) |
| `message` (catch-all) | If `destination` contains master's `node_id`, wrap as BUS and send upstream |
| `message` (shared_bus mode) | Always send as SHARED_BUS to master for passive monitoring |
