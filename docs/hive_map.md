# Hive Map — Topology Discovery and Visualization

`HiveMapper` is the utility class that collects PING-flood responses and builds a
directed graph of the reachable network. It lives in `hivemind_bus_client.hive_map`
and the server imports it in `hivemind_core/protocol.py`.

Discovery is PING-only. A node answers an inbound PING with its own PING carrying the
same `flood_id`. There is no separate PONG message, and the `flood_id` stops infinite
relay loops. On the server the mesh-wide fan-out of that answer is rate-limited by
`ping_flood_interval` (default 30 seconds); inside that window the node answers only the
peer that pinged it. See [Protocol Internals](protocol.md) for the three flood-id caches
involved.

For a conceptual overview of the discovery protocol, see
[HiveMind community docs: network discovery](https://github.com/JarbasHiveMind/HiveMind-community-docs/blob/master/docs/20_network_discovery.md).

---

## Design Overview

```
Originator sends PING (flood_id)
        │
        ▼
HiveMapper.start_ping(flood_id)   ← register expected flood_id
        │
        ▼
PINGs arrive from other nodes (each via PROPAGATE)
        │
        ▼
HiveMapper.on_ping(ping_msg)      ← extract route, upsert nodes/edges
        │
        ▼
HiveMapper.to_ascii()             ← render to terminal
HiveMapper.to_dict()              ← export as a JSON-serializable dict
HiveMapper.to_json()              ← export as a JSON string
```

---

## `HiveMapper` Class

### Constructor

```python
class HiveMapper:
    def __init__(self, max_seen_pings: int = 1000, node_ttl: float = 600.0) -> None:
        """
        Initialize an empty topology map.

        Args:
            max_seen_pings: FIFO bound on the per-flood deduplication index.
            node_ttl: Seconds a node stays in the map after its last PING.

        Attributes:
            nodes (Dict[str, NodeInfo]): peer_id -> node metadata
            edges (Dict[str, Set[str]]): peer_id -> set of peer_ids it was seen routing to
            _seen_pings (OrderedDict[str, Set[str]]): flood_id -> set of peer_ids that already
                sent a PING, FIFO-evicted at max_seen_pings
            _seen_flood_ids (FloodIdCache): already-answered flood ids, for loop prevention.
                It is replaceable, so the two protocol halves of one node can share one store
        """
```

`nodes` and `edges` are not capped. They expire instead: call
`prune_stale_nodes()` to drop what has gone quiet, so a live but silent peer is never
evicted only because it is old.

### `start_ping(flood_id: str) -> None`

Register a new PING session. Clears any stale deduplication state for the given `flood_id`.

```python
mapper.start_ping("550e8400-e29b-41d4-a716-446655440000")
```

### `on_ping(message: HiveMessage, received_at: Optional[float] = None) -> bool`

Ingest a received PING (the inner message of a PROPAGATE wrapper). It reads the sending
node's peer, site_id, timestamp, public_key, and lang from the payload, then walks the
`route` list to upsert directed edges into the adjacency graph.

Returns `True` if the PING was new (not a duplicate), `False` if it was already seen.

```python
from hivemind_bus_client.message import HiveMessage

handled = mapper.on_ping(ping_msg, received_at=time.time())
```

**Route extraction logic:**

```python
for hop in message.route:
    source  = hop["source"]       # str peer_id
    targets = hop["targets"]      # List[str] peer_ids
    # add source -> target edges
```

### `mark_trusted_nodes(trusted_keys: Dict[str, str]) -> None`

Mark each discovered node's `NodeInfo.trusted` flag based on whether its `public_key`
appears in the given alias-to-public-key mapping (for example, `NodeIdentity.trusted_keys`).
Call this after PING discovery completes.

### `is_peer_trusted(peer: str) -> bool`

Return `True` if the given peer was discovered by PING and its `trusted` flag is set.

### `to_dict() -> dict`

Return a JSON-serializable snapshot of the current topology.

```python
{
    "nodes": [
        {
            "peer":        "kitchen-node::abc123",
            "site_id":     "kitchen",
            "timestamp":   1741478400.456,
            "latency_ms":  333.0,
            "public_key":  None,
            "lang":        "en-us",
            "trusted":     False
        },
        ...
    ],
    "edges": [
        { "source": "kitchen-node::abc123", "target": "bedroom-node::def456" },
        ...
    ]
}
```

### `to_json() -> str`

Return `to_dict()` as a formatted JSON string.

### `to_ascii(root_peer: Optional[str] = None) -> str`

Render the topology as a human-readable ASCII tree. PING routes flow toward the
originator, so the mapper stores edges as `relayer -> originator`. Pass `root_peer`
(the local node) to invert the display so the tree reads top-down from the originator
to the leaf nodes, labeled `[self]` at the root.

**Example output:**

```
[self] kitchen-node::abc123
├── bedroom-node::def456  site=bedroom  latency=333ms
│   └── bathroom-node::ghi789  site=bathroom  latency=511ms
└── garage-node::jkl012  site=garage  latency=210ms
```

`latency_ms` on `NodeInfo` is an estimate: receiver clock minus sender clock. It is
not a true round-trip measurement, and it can read negative or inaccurate on
unsynchronized clocks.

### `check_flood_id(flood_id: str, max_size: int = 1000) -> bool`

Check whether `flood_id` was already seen, and register it. The first call for a
given `flood_id` returns `False` (not seen). Later calls return `True`. When the
cache passes `max_size`, the oldest entries are evicted first (FIFO).

### `prune_stale_nodes(now: Optional[float] = None) -> None`

Drop every node, and its edges, not heard from within `node_ttl` seconds. Pass `now` to
use a clock other than `time.time()`.

```python
mapper.prune_stale_nodes()
```

### `clear() -> None`

Reset the mapper to an empty state (nodes, edges, seen-ping and seen-flood-id
deduplication).

---

## `NodeInfo` Dataclass

```python
@dataclass
class NodeInfo:
    peer:        str
    site_id:     Optional[str]   = None
    timestamp:   Optional[float] = None    # sender's clock when it created the PING
    received_at: Optional[float] = None    # local clock when we received it
    public_key:  Optional[str]   = None    # RSA public key, if provided in the PING
    lang:        Optional[str]   = None    # locale announced by the node (e.g. "en-us")
    trusted:     bool            = False   # whether this peer's key is in the trusted list

    @property
    def latency_ms(self) -> Optional[float]:
        """Estimated one-way latency in milliseconds, or None if timestamps are unavailable."""
        if self.received_at is not None and self.timestamp is not None:
            return (self.received_at - self.timestamp) * 1000
        return None
```

---

## Integration with `HiveMindListenerProtocol`

The server-side protocol creates a `HiveMapper` instance and feeds it PINGs:

```python
# hivemind_core/protocol.py

def handle_ping_message(self, message: HiveMessage, client: HiveMindClientConnection) -> None:
    """
    Feed the PING into the local HiveMapper. Emit hive.ping.received only for
    a peer new to the map, then relay this node's own responsive PING (same
    flood_id) — to every connected peer and upstream once per
    ping_flood_interval, and to the asking peer alone inside that window.
    """
    new_to_map = self.hive_mapper.on_ping(message, received_at=time.time())
    if new_to_map:
        self.agent_protocol.bus.emit(Message("hive.ping.received", {...}))
    if self._answered_floods.check(flood_id):
        return
    if now - self._last_ping_flood < self.ping_flood_interval:
        client.send(own_ping_outer)   # answer the asker only
        return
    for peer_id, conn in self.clients.items():
        conn.send(own_ping_outer)
```

---

## Standalone Usage Example

```python
import time
import uuid
from hivemind_bus_client import HiveMessageBusClient
from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivemind_bus_client.hive_map import HiveMapper

client = HiveMessageBusClient()
client.run_in_thread()
client.connected_event.wait()

mapper    = HiveMapper()
flood_id  = str(uuid.uuid4())
mapper.start_ping(flood_id)

def on_ping(message):
    if message.payload.get("flood_id") == flood_id:
        mapper.on_ping(message, received_at=time.time())

client.on(HiveMessageType.PING, on_ping)

# Send PING
ping_payload = {
    "flood_id":  flood_id,
    "timestamp": time.time(),
    "peer":      client.peer,
    "site_id":   client.site_id,
}
ping_msg = HiveMessage(HiveMessageType.PROPAGATE,
                       payload=HiveMessage(HiveMessageType.PING, ping_payload))
client.emit(ping_msg)

# Collect for 5 seconds
time.sleep(5)

print(mapper.to_ascii(root_peer=client.peer))
print(mapper.to_json())
```

---

## File Location

| File | Purpose |
|---|---|
| `hivemind_bus_client/hive_map.py` | `HiveMapper` and `NodeInfo` implementation |
| `hivemind_core/protocol.py` | `handle_ping_message()` handler that feeds the mapper |

---

## Related Documents

- [Protocol Internals](protocol.md): handler lifecycle and message routing.
- [HiveMind community docs: network discovery](https://github.com/JarbasHiveMind/HiveMind-community-docs/blob/master/docs/20_network_discovery.md): conceptual overview.
- [hivemind-websocket-client: CLI guide](https://github.com/JarbasHiveMind/hivemind-websocket-client/blob/dev/docs/cli_guide.md): the `hivemind-client ping` command.

---
[← Plugin Development](plugin_development.md) · [Home](index.md) · [Ecosystem →](ecosystem.md)
