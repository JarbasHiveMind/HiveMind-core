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
| Timeout behavior | Agent can't handle → escalate upstream | Originator-side aggregation |
| Aggregation | N/A (single response) | `CascadeAggregator` (client-side) |

---

## QUERY Flow

```
Satellite → QUERY(BUS) → Hub
Hub: agent_protocol.handle_query(bus_msg, callback, timeout=5.0)
  ├─ Agent answers → callback(response) → QUERY(BUS) back to satellite
  └─ Timeout → query_to_master(payload) → escalate upstream
```

Direction is implicit — no `query_id` or `is_response` metadata required.

`AgentProtocol.handle_query` default is a no-op; agents that don't override cause QUERY to always escalate.
Source: `AgentProtocol.handle_query` — `hivemind_plugin_manager/protocols.py`

---

## CASCADE Flow

```
Satellite → CASCADE(BUS) → Hub
Hub:
  1. Inject inner BUS into local agent bus (same as PROPAGATE)
  2. Forward CASCADE to all other connected clients
  3. Forward upstream if relay (cascade_to_master)
  4. All nodes emit BUS responses naturally via session context
  5. CascadeAggregator on originating satellite collects responses
```

Source: `handle_cascade_message` — `protocol.py`, `CascadeAggregator` — `hivemind_bus_client`

---

## Permission Gates

- QUERY: `client.can_escalate` — violation → `client.disconnect()` + `illegal_callback`
- CASCADE: `client.can_propagate` — violation → `client.disconnect()` + `illegal_callback`

---

## Relay Behaviour

- `query_to_master(payload)`: wraps payload in `QUERY` and emits to upstream `_upstream_hm`
- `cascade_to_master(payload)`: wraps payload in `CASCADE` and emits to upstream `_upstream_hm`
- Both are no-ops when `_upstream_hm is None`

Source: `query_to_master`, `cascade_to_master` — `protocol.py`
