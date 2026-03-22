# QUERY and CASCADE Message Types

Request-response extensions to the HiveMind transport protocol. While ESCALATE and PROPAGATE are fire-and-forget, QUERY and CASCADE return answers to the originator.

Source: `handle_query_message` — `protocol.py`, `handle_cascade_message` — `protocol.py`

---

## Overview

| Aspect | QUERY | CASCADE |
|--------|-------|---------|
| Base pattern | ESCALATE (upstream only) | PROPAGATE (all directions) |
| Response count | First answer wins | All nodes respond |
| ACL permission | `can_escalate` | `can_propagate` |
| Timeout behavior | Per-hop: agent can't handle → escalate further | Originator-side: collect until satisfied |
| Disambiguation | N/A (single response) | `cascade_select_callback` |
| Bus event (request) | `hive.query.received` | `hive.cascade.received` |
| Bus event (no answer) | `hive.query.timeout` | — |

---

## Payload Format

Both use existing `HiveMessage` structure. Correlation and response tracking live in `metadata`:

```python
from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message
import uuid

bus_msg = Message("recognizer_loop:utterance", {"utterances": ["what is 2+2?"]})
inner = HiveMessage(HiveMessageType.BUS, payload=bus_msg)

query = HiveMessage(
    HiveMessageType.QUERY,  # or CASCADE
    payload=inner,
    metadata={
        "query_id": str(uuid.uuid4()),     # correlation ID
        "originator_peer": "my_peer_id",   # who started the query
        "is_response": False,              # False=request, True=response
    },
)
```

No new `HiveMessageType` values needed. Responses reuse the same type (QUERY/CASCADE) with `is_response=True`.

### Metadata Fields

| Field | Required | Request | Response | Description |
|-------|----------|---------|----------|-------------|
| `query_id` | yes | ✓ | ✓ | UUID correlation ID, set by originator |
| `originator_peer` | yes | ✓ | ✓ | Peer that started the query (for routing) |
| `is_response` | yes | `False` | `True` | Distinguishes request from response |
| `responder_peer` | — | — | ✓ | Peer that generated this answer |
| `responder_site_id` | — | — | ✓ | Site ID of the responder |

---

## QUERY Algorithm

### Request Flow (is_response=False)

```
1. Satellite builds QUERY(BUS(utterance), metadata={query_id, originator_peer, is_response=False})
2. Sends upstream to master

3. Master receives QUERY request:
   a. ACL check: client.can_escalate (reuses ESCALATE permission)
   b. Inject inner BUS into local agent bus with context["query_id"]
   c. Listen for synchronous agent response (same call stack)
   d. IF agent responds:
      → Build QUERY(is_response=True) response
      → Send back to client (toward originator)
      → STOP — do NOT escalate further
   e. IF no response:
      → Forward QUERY upstream via query_to_master()
      → If no upstream (top-level master): send error response
```

### Response Flow (is_response=True)

```
1. Master receives QUERY response from upstream
2. Check if originator_peer is a direct client:
   → Yes: send directly to them
   → No: forward to all downstream clients (next hop routing)
3. Satellite receives QUERY response:
   → Unwrap inner BUS payload → emit on internal bus
```

### Synchronous Response Detection

`_try_local_agent_query` (`protocol.py`) injects the BUS message with `context["query_id"]` set. A `"message"` catch-all listener on the bus captures any response that has a matching `query_id` in its context. The listener skips the injected message itself (matched by `msg_type`).

This is synchronous: if no handler on the FakeBus produces a response in the same call stack, the query is considered unanswered.

---

## CASCADE Algorithm

### Request Flow (is_response=False)

```
1. Satellite builds CASCADE(BUS(utterance), metadata={query_id, originator_peer, is_response=False})
2. Sends upstream to master

3. Master receives CASCADE request:
   a. ACL check: client.can_propagate (reuses PROPAGATE permission)
   b. Inject inner BUS into local agent bus
   c. Forward CASCADE to ALL other downstream peers
   d. Forward CASCADE upstream (if relay)
   e. When local agent responds:
      → Build CASCADE(is_response=True)
      → Route via _route_query_response (supports disambiguation)
```

### Response Flow (is_response=True)

```
1. Master receives CASCADE response:
   a. If cascade_select_callback is set AND originator is direct client:
      → Add to CascadeCollector (keyed by query_id)
      → Invoke callback(query_id, responses)
      → If callback returns Message → emit on bus, clean up
      → If callback returns None → wait for more
   b. Otherwise: forward toward originator (same as QUERY)

2. Satellite receives CASCADE response:
   → Unwrap inner BUS → emit on internal bus
```

---

## Disambiguation (CASCADE only)

When multiple nodes respond to a CASCADE, the originator needs a way to pick the best answer. `cascade_select_callback` provides this.

### CascadeResponse

```python
@dataclass
class CascadeResponse:
    responder_peer: str          # who responded
    responder_site_id: str       # their site ID
    messages: List[Message]      # OVOS Messages (e.g., speak)
    metadata: dict               # full response metadata
```

### CascadeCollector

Accumulates responses per `query_id`. Each new response triggers the callback.

### Setting Up Disambiguation

```python
from hivemind_core.protocol import CascadeResponse
from ovos_bus_client.message import Message
from typing import List, Optional

def select_best(query_id: str, responses: List[CascadeResponse]) -> Optional[Message]:
    """Called each time a CASCADE response arrives for this query_id.

    Return a Message to emit on the bus (finalizes the query).
    Return None to keep waiting for more responses.
    """
    if len(responses) < 3:
        return None  # wait for at least 3 answers

    # Example: pick the response with the longest utterance
    best = max(responses, key=lambda r:
        len(r.messages[0].data.get("utterance", "")) if r.messages else 0)
    return best.messages[0] if best.messages else None

hm_protocol.cascade_select_callback = select_best
```

### Without Disambiguation

If `cascade_select_callback` is not set, every CASCADE response is forwarded directly to the originating satellite. The satellite receives multiple QUERY responses and can handle them in application code.

---

## Relay Support

Both QUERY and CASCADE work through relay chains. The relay's master side processes the message (local agent check + forwarding), and the relay's satellite side sends/receives from the upstream master.

### Relay Registration

`bind_upstream()` registers handlers for downstream forwarding:

```python
slave.hm.on(HiveMessageType.QUERY, self.query_from_master)
slave.hm.on(HiveMessageType.CASCADE, self.cascade_from_master)
```

### Upstream Forwarding

```python
def query_to_master(self, payload, metadata):
    self._upstream_hm.emit(HiveMessage(QUERY, payload=payload, metadata=metadata))

def cascade_to_master(self, payload, metadata):
    self._upstream_hm.emit(HiveMessage(CASCADE, payload=payload, metadata=metadata))
```

---

## Satellite-Side Handlers

`HiveMindSlaveProtocol` (`hivemind_bus_client/protocol.py`) registers:

```python
self.hm.on(HiveMessageType.QUERY, self.handle_query)
self.hm.on(HiveMessageType.CASCADE, self.handle_cascade)
```

Both handlers follow the same pattern:
- **Response** (`is_response=True`): unwrap inner BUS payload → `handle_bus()` → emit on internal OVOS bus
- **Request** (`is_response=False`): forward downstream via `hive.send.downstream` (for relay scenarios)

---

## Embedded Client Support

### JavaScript (HiveMind-js)

Callbacks: `onHiveQuery(msg)`, `onHiveCascade(msg)`. For responses, inner BUS payload is automatically unwrapped and emitted via `onMycroftMessage` / `onMycroftSpeak`.

### MicroPython

Already handled in the combined dispatch: `msg_type in ("bus", "shared_bus", "broadcast", "escalate", "query", "cascade")` → calls `on_bus_message` callback.

### ESP32

No changes needed — protocol layer handles encrypt/decrypt only.

---

## Bus Events

| Event | When | Data |
|-------|------|------|
| `hive.query.received` | Master receives QUERY request | `query_id`, `originator_peer` |
| `hive.query.timeout` | Top-level master has no answer | `query_id`, `error: "no_answer"` |
| `hive.cascade.received` | Master receives CASCADE request | `query_id`, `originator_peer` |

---

## ACL & Security

- QUERY reuses `can_escalate` permission (same upstream-only pattern)
- CASCADE reuses `can_propagate` permission (same flood pattern)
- Unauthorized sends trigger `illegal_callback` + `client.disconnect()`
- All messages are encrypted after handshake (same transport layer as other types)
- `_try_local_agent_query` respects `client.authorize()` and blacklists
