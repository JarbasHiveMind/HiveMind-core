Last Edit: Claude Sonnet 4.6 - 2026-03-09 - Motive: Added PING/PONG handler specifications and HiveMapper integration.

# Protocol Internals

This document describes the server-side protocol classes that process HiveMind connections.

## Protocol versions

| Version | Features |
|---|---|
| `0` | JSON only, no handshake, no binary |
| `1` | Password-based handshake, AES session encryption |
| `2` | Binary serialisation support |

## Connection lifecycle

```
Client connects (network layer)
        │
        ▼
HiveMindListenerProtocol.handle_new_client()
  ├─ emits hive.client.connect on agent bus
  ├─ sends HELLO  (server pubkey + peer id)
  └─ sends HANDSHAKE  (capabilities, crypto requirements)
        │
        ▼
Client sends HANDSHAKE (pubkey or password envelope)
        │
HiveMindListenerProtocol.handle_handshake_message()
  ├─ derives session AES key
  └─ sends HANDSHAKE response (envelope + chosen cipher/encoding)
        │
        ▼
Client sends HELLO  (session, site_id, client pubkey)
        │
HiveMindListenerProtocol.handle_hello_message()
  └─ registers client in self.clients
        │
        ▼
Normal message exchange
        │
        ▼
Client disconnects
  └─ HiveMindListenerProtocol.handle_client_disconnected()
       emits hive.client.disconnect on agent bus
```

---

## `HiveMindListenerProtocol`

The core message router. Instantiated once per server; shared by all network protocol plugins.

```python
from hivemind_core.protocol import HiveMindListenerProtocol
```

### Key attributes

| Attribute | Type | Description |
|---|---|---|
| `agent_protocol` | `AgentProtocol` | Handles message payloads (OVOS, Persona, …) |
| `binary_data_protocol` | `BinaryDataHandlerProtocol` | Handles binary payloads |
| `db` | `ClientDatabase` | Credential storage |
| `identity` | `NodeIdentity` | This node's RSA keypair / peer ID |
| `clients` | `dict[str, HiveMindClientConnection]` | Currently connected clients keyed by peer ID |
| `require_crypto` | `bool` | Reject connections without encryption (default `True`) |
| `handshake_enabled` | `bool` | Negotiate a per-session key when no pre-shared key exists |

### Message handlers

| Method | Triggered when |
|---|---|
| `handle_new_client(client)` | A new connection is accepted by the network layer |
| `handle_client_disconnected(client)` | A connection is closed |
| `handle_message(message, client)` | Any inbound `HiveMessage` is received |
| `handle_handshake_message(message, client)` | `HiveMessageType.HANDSHAKE` received |
| `handle_hello_message(message, client)` | `HiveMessageType.HELLO` received |
| `handle_bus_message(message, client)` | `HiveMessageType.BUS` received |
| `handle_propagate_message(message, client)` | `HiveMessageType.PROPAGATE` received |
| `handle_broadcast_message(message, client)` | `HiveMessageType.BROADCAST` received |
| `handle_escalate_message(message, client)` | `HiveMessageType.ESCALATE` received |
| `handle_intercom_message(message, client)` | `HiveMessageType.INTERCOM` received |
| `handle_binary_message(message, client)` | `HiveMessageType.BINARY` received |
| `handle_ping_message(message, client)` | `HiveMessageType.PING` inner payload received (unwrapped from PROPAGATE) |
| `handle_pong_message(message, client)` | `HiveMessageType.PONG` inner payload received (unwrapped from PROPAGATE) |

### PING / PONG handler behaviour

#### `handle_ping_message(message, client)`

Called when a PROPAGATE message's inner payload is a PING.

All nodes SHOULD relay the PING to all connected peers (except the sender) and MAY respond with a
PONG. Whether to respond is a node-level policy decision — for example, a master may be configured
to act as a discovery boundary and silently drop the PING rather than relaying it further upstream.

```
Receive PROPAGATE(PING)
  ├─ relay PROPAGATE(PING) to all connected peers except sender   [SHOULD]
  └─ build PROPAGATE(PONG) and send back toward originator        [MAY — node policy]
```

See [network discovery docs](../../HiveMind-community-docs/docs/20_network_discovery.md) for the
full design rationale and wire format.

#### `handle_pong_message(message, client)`

Called when a PROPAGATE message's inner payload is a PONG.

1. Feed the PONG into the local `HiveMapper` instance (`self.hive_mapper.on_pong(message)`).
2. Emit `hive.pong.received` on the agent bus with the PONG payload.
3. Relay the PONG onward via PROPAGATE (standard propagation semantics).

The originating node collects PONGs until its timeout expires, then calls
`HiveMapper.to_ascii()` / `to_dict()` to read the topology.

### Optional callbacks

These can be set on the protocol instance to intercept events without subclassing:

```python
protocol.escalate_callback  = lambda msg: ...  # message escalated upstream
protocol.propagate_callback = lambda msg: ...  # message propagated to peers
protocol.broadcast_callback = lambda msg: ...  # message broadcast (admin only)
protocol.agent_bus_callback = lambda msg: ...  # message injected into agent bus
protocol.shared_bus_callback = lambda msg: ... # passive bus share from a client
protocol.illegal_callback   = lambda msg: ...  # client attempted illegal action
```

---

## `HiveMindClientConnection`

Represents a single active connection.

```python
from hivemind_core.protocol import HiveMindClientConnection
```

### Key attributes

| Attribute | Type | Description |
|---|---|---|
| `key` | `str` | API access key used to look up this client in the database |
| `peer` | `str` | Unique identifier (`name::session_id`) used in message routing |
| `sess` | `Session` | OVOS session associated with this client |
| `crypto_key` | `str \| None` | AES session key (set after handshake) |
| `is_admin` | `bool` | Whether this client has admin privileges |
| `can_escalate` | `bool` | Client may send ESCALATE messages |
| `can_propagate` | `bool` | Client may send PROPAGATE messages |
| `msg_blacklist` | `list[str]` | OVOS message types never forwarded to this client |
| `skill_blacklist` | `list[str]` | Skill IDs blocked for this client |
| `intent_blacklist` | `list[str]` | Intent IDs blocked for this client |
| `allowed_types` | `list[str]` | OVOS message types this client may inject |
| `binarize` | `bool` | Use binary serialisation with this client |

### Key methods

| Method | Description |
|---|---|
| `send(message)` | Encrypt and transmit a `HiveMessage` to this client |
| `decode(payload)` | Decrypt and deserialise a received payload into a `HiveMessage` |
| `authorize(message)` | Return `True` if this client is allowed to inject the given message |

---

## `HiveMindService`

Top-level service class. Loads plugins from configuration and starts all network listeners.

```python
from hivemind_core.service import HiveMindService

service = HiveMindService()
service.run()  # blocks until Ctrl-C
```

The service wires together:

1. One `AgentProtocol` instance
2. One `BinaryDataHandlerProtocol` instance
3. One `HiveMindListenerProtocol` instance
4. One or more `NetworkProtocol` instances (each runs in a daemon thread)

---

## `ClientDatabase`

Thin wrapper around the configured database plugin.

```python
from hivemind_core.database import ClientDatabase

with ClientDatabase() as db:
    db.add_client("my-satellite", access_key="abc", password="xyz")
    client = db.get_client_by_api_key("abc")
    print(client.name, client.is_admin)
```

### Methods

| Method | Description |
|---|---|
| `add_client(name, key, ...)` | Add or update a client record |
| `get_client_by_api_key(key)` | Look up a `Client` by access key |
| `get_clients_by_name(name)` | Find clients by name |
| `delete_client(key)` | Delete a client by access key |
| `update_item(client)` | Persist changes to an existing `Client` object |
| `total_clients()` | Number of registered clients |
| `sync()` | Reload the database from disk if needed |

The context manager (`with ClientDatabase() as db`) commits changes on exit.

---

## Node types

| Type | Description |
|---|---|
| `CANDIDATE_NODE` | Connecting but not yet authenticated |
| `NODE` | Any authenticated connection |
| `MIND` | A hub listening for connections |
| `SLAVE` | A node that can be partially controlled by a mind |
| `TERMINAL` | User-facing endpoint that does not accept connections |
| `BRIDGE` | Connects an external service to the hive |
| `FAKECROFT` | A mind using a non-Mycroft AI backend |
