# Protocol Internals

This document describes the server-side protocol classes that process HiveMind connections.

## Protocol versions

| Version | Features |
|---|---|
| `0` | JSON only, no handshake, no binary |
| `1` | Password-based handshake, AES session encryption |
| `2` | Binary serialisation support |
| `3` | Noise handshake (XXpsk2/KKpsk0) with authenticated, forward-secret transport; falls back to v2 against older clients |

The server admits a client only if the version it negotiates is at least
`min_protocol_version` (default `2`) from `server.json`. The check runs when the handshake
completes, not only when the server advertises the floor. The advertised floor is the
higher of the configured value and the value the crypto settings need.

## Connection lifecycle

```
Client connects (network layer)
        │
        ▼
HiveMindListenerProtocol.handle_new_client()
  ├─ moves the connection off the reserved "default" session
  ├─ emits hive.client.connect on agent bus
  ├─ computes min/max protocol version, drops the client if they do not overlap
  ├─ sends HELLO  (server pubkey + peer id)
  └─ sends HANDSHAKE  (capabilities, crypto requirements)
        │
        ▼
Client sends HANDSHAKE (pubkey or password envelope)
        │
HiveMindListenerProtocol.handle_handshake_message()
  ├─ derives session AES key
  ├─ drops the client if the agreed version is below min_protocol_version
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
| `require_crypto` | `bool` | Require proof of origin (default `True`). While it is true, an `INTERCOM` frame with no signed envelope is dropped, not relayed and not escalated. This is an attribute, not a `server.json` key |
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
| `handle_query_message(message, client)` | `HiveMessageType.QUERY` received |
| `handle_cascade_message(message, client)` | `HiveMessageType.CASCADE` received |
| `handle_ping_message(message, client)` | `HiveMessageType.PING` inner payload received (unwrapped from PROPAGATE) |
| `handle_noise_handshake_message(message, client)` | A protocol v3 Noise handshake frame is received |
| `handle_client_shared_bus(message, client)` | `HiveMessageType.SHARED_BUS` received |
| `handle_invalid_key_connected(client)` | A client presents an access key that is not in the database |
| `handle_invalid_protocol_version(client)` | A client negotiates below `min_protocol_version` |
| `handle_unknown_message(message, client)` | The message type matches no handler |

### PING handler behaviour

#### `handle_ping_message(message, client)`

Called when a PROPAGATE message's inner payload is a PING.

Discovery is PING-only. There is no PONG message. The handler feeds the PING into the
local `HiveMapper`, which answers whether this `(flood_id, peer)` pair is new. Only a new
pair emits `hive.ping.received` on the agent bus, so a peer that reaches this node over
several mesh paths is reported once, not once per path.

The handler then builds its own responsive PING carrying the same `flood_id`, and decides
who gets it. Two caches decide the answer; a third, `_forwarded_flood_ids`, gates the
PROPAGATE fan-out around it:

| Cache | Scope | Question it answers |
|---|---|---|
| `_answered_floods` | private to this protocol half | Has this half already answered this flood? |
| `_seen_flood_ids` | shared with the upstream slave protocol through `bind_flood_cache` | Has the node, as a whole, already claimed this flood? It keeps the two halves counted as one node in remote maps |
| `_forwarded_flood_ids` | private | Has this **node** already forwarded this flood? Consulted by `handle_propagate_message` before the fan-out, not by the PING answer logic. Dedup is per node, never per peer |

The mesh-wide fan-out is rate-limited by `ping_flood_interval` (default 30 seconds).
Inside that window the node answers **only the peer that pinged it**, with one send, so
that peer's map is still correct. Outside the window the responsive PING goes to every
connected peer and upstream.

```
Receive PROPAGATE(PING)
  ├─ hive_mapper.on_ping(message)
  ├─ if new to the map: emit hive.ping.received on the agent bus
  ├─ if _answered_floods already holds flood_id: stop
  └─ send PROPAGATE(PING) with the same flood_id
       ├─ inside ping_flood_interval: to the asking peer only
       └─ otherwise: to all peers and upstream
```

The node that started the flood collects the answering PINGs until its timeout expires,
then calls `HiveMapper.to_ascii()` or `to_dict()` to read the topology. See
[Hive Map](hive_map.md) for the mapper API.

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
| `peer` | `str` | Unique identifier (`name::session_id`) used in message routing. If another live connection already owns that string, the server appends a suffix to keep the two apart |
| `sess` | `Session` | OVOS session associated with this client |
| `crypto_key` | `str \| None` | AES session key (set after handshake) |
| `is_admin` | `bool` | Whether this client has admin privileges |
| `can_escalate` | `bool` | Client may send ESCALATE messages |
| `can_propagate` | `bool` | Client may send PROPAGATE messages |
| `allowed_types` | `list[str]` | OVOS message types this client may inject. The only ACL field on the connection |
| `binarize` | `bool` | Use binary serialisation with this client |
| `site_id` | `str` | Site this client belongs to |
| `noise_transport` | `NoiseTransport \| None` | Session layer on a protocol v3 connection. Replaces `crypto_key` |

There is no message, skill, or intent blacklist on the connection. `allowed_types` is
whitelist-only and deny-by-default. Skill and intent blacklists live in `Client.metadata`
and `OVOSAgentPolicy` reads them.

### Key methods

| Method | Description |
|---|---|
| `send(message)` | Encrypt and transmit a `HiveMessage` to this client |
| `decode(payload)` | Decrypt and deserialise a received payload into a `HiveMessage` |
| `authorize(message)` | Subclass hook. Returns `True` by default. The `allowed_types` check moved to `MessageTypeACLPolicy` |
| `resolve_user(db)` | Return the cached database row for this connection, refetching at most once per TTL window |

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
    db.add_client("my-satellite", key="abc", password="xyz")
    client = db.get_client_by_api_key("abc")
    print(client.name, client.is_admin)
```

### Methods

| Method | Description |
|---|---|
| `add_client(name, key, ...)` | Add or update a client record. The access key is the `key` argument |
| `get_client_by_id(client_id)` | Look up a `Client` by numeric node id |
| `refresh(client_id)` | Refetch a `Client` row from the backend |
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
| `MIND` | A server node listening for connections |
| `SLAVE` | A node that another node can partially control |
| `TERMINAL` | User-facing endpoint that does not accept connections |
| `BRIDGE` | Connects an external service to the network |
| `FAKECROFT` | A `MIND` node using a non-Mycroft AI backend |

---
[← Security](security.md) · [Home](index.md) · [CLI Reference →](cli.md)
