Last Edit: Claude Sonnet 4.6 - 2026-03-09 - Motive: Initial specification for HiveMapper topology class and visualization utilities.

# Hive Map — Topology Discovery and Visualization

`HiveMapper` is the utility class that collects PONG responses from a PING flood and builds a
directed graph of the reachable hive. It is defined in `hivemind_core.hive_map`.

For a conceptual overview of the PING/PONG protocol, see
[`HiveMind-community-docs: docs/20_network_discovery.md`](../../HiveMind-community-docs/docs/20_network_discovery.md).

---

## Design Overview

```
Originator sends PING
        │
        ▼
HiveMapper.start_ping(ping_id)   ← register expected ping_id
        │
        ▼
PONGs arrive (each via PROPAGATE)
        │
        ▼
HiveMapper.on_pong(pong_msg)     ← extract route, upsert nodes/edges
        │
        ▼
HiveMapper.to_ascii()            ← render to terminal
HiveMapper.to_dict()             ← export as JSON-serialisable dict
HiveMapper.to_json()             ← export as JSON string
```

---

## `HiveMapper` Class

### Constructor

```python
class HiveMapper:
    def __init__(self) -> None:
        """
        Initialise an empty topology map.

        Attributes:
            nodes (Dict[str, NodeInfo]): peer_id → node metadata
            edges (Dict[str, Set[str]]): peer_id → set of peer_ids it was seen routing to
            _seen_pongs (Dict[str, Set[str]]): ping_id → set of peer_ids that already responded
        """
```

### `start_ping(ping_id: str) -> None`

Register a new PING session. Clears any stale PONG-deduplication state for the given `ping_id`.

```python
mapper.start_ping("550e8400-e29b-41d4-a716-446655440000")
```

### `on_pong(message: HiveMessage) -> bool`

Ingest a received PONG (the inner message of a PROPAGATE wrapper). Extracts the responding node's
peer, site_id, and pong_timestamp from the payload, then walks the `route` list to upsert directed
edges into the adjacency graph.

Returns `True` if the PONG was new (not a duplicate), `False` if it was already seen.

```python
from hivemind_bus_client.message import HiveMessage

handled = mapper.on_pong(pong_msg)
```

**Route extraction logic:**

```python
for hop in message.route:
    source  = hop["source"]       # str peer_id
    targets = hop["targets"]      # List[str] peer_ids
    # add source → target edges
```

### `to_dict() -> dict`

Return a JSON-serialisable snapshot of the current topology.

```python
{
    "nodes": [
        {
            "peer":           "kitchen-node::abc123",
            "site_id":        "kitchen",
            "pong_timestamp": 1741478400.456
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

### `to_ascii() -> str`

Render the topology as a human-readable tree rooted at the local node. Uses the `rich` library when
available for colour and box-drawing characters; falls back to plain ASCII.

**Example output (plain):**

```
[self] kitchen-node::abc123
├── bedroom-node::def456  (site: bedroom)
│   └── bathroom-node::ghi789  (site: bathroom)
└── garage-node::jkl012  (site: garage)
```

**Example output (rich):**

```
┌─ [self] kitchen-node::abc123
├─── bedroom-node::def456        site=bedroom  rtt=333ms
│    └─── bathroom-node::ghi789  site=bathroom rtt=511ms
└─── garage-node::jkl012         site=garage   rtt=210ms
```

RTT (round-trip time) is computed as `pong_timestamp − ping_timestamp` when both are available.

### `clear() -> None`

Reset the mapper to an empty state (nodes, edges, seen-pong deduplication).

---

## `NodeInfo` Dataclass

```python
@dataclass
class NodeInfo:
    peer:           str
    site_id:        Optional[str]   = None
    pong_timestamp: Optional[float] = None
    ping_timestamp: Optional[float] = None

    @property
    def rtt_ms(self) -> Optional[float]:
        """Round-trip time in milliseconds, or None if timestamps unavailable."""
        if self.pong_timestamp is not None and self.ping_timestamp is not None:
            return (self.pong_timestamp - self.ping_timestamp) * 1000
        return None
```

---

## Integration with `HiveMindListenerProtocol`

The server-side protocol creates a `HiveMapper` instance and feeds it PONGs:

```python
# hivemind_core/protocol.py (planned)

def handle_pong_message(self, message: HiveMessage, client: HiveMindClientConnection) -> None:
    """
    Relay PONG upstream/downstream via PROPAGATE, then ingest into the local HiveMapper.

    Args:
        message: The inner PONG HiveMessage (already unwrapped from PROPAGATE).
        client:  The client connection that delivered this message.
    """
    self.hive_mapper.on_pong(message)
    self.agent_bus.emit(Message("hive.pong.received", data=message.payload))
    # relay onward (PROPAGATE semantics)
    self._relay_propagate(message, client)
```

---

## Standalone Usage Example

```python
import time
import uuid
from hivemind_bus_client import HiveMessageBusClient
from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivemind_core.hive_map import HiveMapper

client = HiveMessageBusClient()
client.run_in_thread()
client.connected_event.wait()

mapper  = HiveMapper()
ping_id = str(uuid.uuid4())

def on_pong(message):
    if message.payload.get("ping_id") == ping_id:
        mapper.on_pong(message)

client.on(HiveMessageType.PONG, on_pong)

# Send PING
ping_payload = {
    "ping_id":   ping_id,
    "timestamp": time.time(),
    "peer":      client.peer,
    "site_id":   client.site_id,
}
ping_msg = HiveMessage(HiveMessageType.PROPAGATE,
                       payload=HiveMessage(HiveMessageType.PING, ping_payload))
client.emit(ping_msg)

# Collect for 5 seconds
time.sleep(5)

print(mapper.to_ascii())
print(mapper.to_json())
```

---

## File Location

| File | Purpose |
|---|---|
| `hivemind_core/hive_map.py` | `HiveMapper` and `NodeInfo` implementation |
| `hivemind_core/protocol.py` | `handle_ping_message()` and `handle_pong_message()` handlers |

---

## Related Documents

- [Protocol Internals](protocol.md) — Handler lifecycle and message routing
- [`HiveMind-community-docs: 20_network_discovery.md`](../../HiveMind-community-docs/docs/20_network_discovery.md) — Conceptual overview
- [`hivemind-websocket-client: docs/cli_guide.md`](../../hivemind-websocket-client/docs/cli_guide.md) — `hivemind-client ping` command
