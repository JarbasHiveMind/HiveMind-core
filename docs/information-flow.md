# Information Flow & Topology-Driven Security

The HiveMind protocol is designed around a single principle: **message behavior is fully determined by message type and topology position**. There are no runtime configuration flags that change routing — the topology itself *is* the security policy.

Source: `HiveMindListenerProtocol` — `protocol.py`, `HiveMindSlaveProtocol` — `hivemind_bus_client/protocol.py`

---

## The Three Directions

Every message in HiveMind flows in exactly one of three directions relative to the sending node:

| Direction | Meaning | Who can send | Example |
|-----------|---------|-------------|---------|
| **Upstream** | Toward the authority chain (master → master's master → …) | Satellites only | ESCALATE, QUERY, BUS |
| **Downstream** | Toward connected satellites | Masters only | BUS (response), BROADCAST |
| **Flood** | All directions — upstream + all downstream peers | Any node | PROPAGATE, CASCADE, PING |

A node's **role in the topology** determines which directions are available to it:

```
           UPSTREAM (authority)
               ↑
    Master ────┤──── DOWNSTREAM (satellites)
               │
    Satellite ─┘
               ↑
           UPSTREAM only
```

---

## Direction Semantics Per Message Type

### Upstream-Only Messages

These climb the authority chain and are **never forwarded to sibling satellites**.

| Type | Inner payload | Response? | Permission |
|------|--------------|-----------|------------|
| **ESCALATE** | HiveMessage (any) | No | `can_escalate` |
| **QUERY** | HiveMessage(BUS) | Yes — first answer wins | `can_escalate` |
| **BUS** | OVOS Message | Implicit (via `destination` routing) | `allowed_types` |

**Security property**: A satellite can never inject messages into a sibling satellite's bus via ESCALATE/QUERY. The master processes the message and decides what (if anything) to forward. Siblings are isolated.

### Downstream-Only Messages

These flow from master to connected satellites and **never propagate upstream**.

| Type | Inner payload | Permission |
|------|--------------|------------|
| **BROADCAST** | HiveMessage (any) | `is_admin` |
| **BUS** (response) | OVOS Message | Implicit (master→satellite via `destination`) |

**Security property**: Only admin clients can initiate BROADCAST. Non-admin satellites cannot cause messages to appear on sibling satellites' buses via BROADCAST.

### Flood Messages (Bidirectional)

These propagate in all directions — to all connected peers AND upstream.

| Type | Inner payload | Response? | Permission |
|------|--------------|-----------|------------|
| **PROPAGATE** | HiveMessage (any) | No | `can_propagate` |
| **CASCADE** | HiveMessage(BUS) | Yes — all nodes respond | `can_propagate` |
| **PING** | dict (flood payload) | Implicit (responsive PING) | (via PROPAGATE) |

**Security property**: Flood messages are the most powerful — they reach every node in the hive. This is why `can_propagate` is a distinct permission. Revoking it prevents a compromised satellite from flooding the network.

---

## Topology as Security Policy

### The Authority Chain

```
M0 (root master)
├── R1 (relay: satellite of M0, master of S0/S1)
│   ├── S0 (leaf satellite)
│   └── S1 (leaf satellite)
└── S2 (leaf satellite of M0)
```

In this topology:

- **S0 can reach M0** via ESCALATE/QUERY through R1 (upstream chain)
- **S0 cannot reach S1** directly — only via PROPAGATE/CASCADE (flood through R1)
- **S0 cannot reach S2** directly — only via PROPAGATE/CASCADE (flood through R1 → M0 → S2)
- **M0 can reach all nodes** via BROADCAST (downstream flood)
- **R1 can reach S0/S1** as their master, AND M0 as its master's satellite

### Permission Matrix

| Sender | `can_escalate` | `can_propagate` | `is_admin` | Reachable nodes |
|--------|---------------|----------------|-----------|-----------------|
| S0 (default) | ✓ | ✓ | ✗ | M0 (via ESCALATE), all (via PROPAGATE) |
| S0 (restricted) | ✗ | ✗ | ✗ | None (only BUS to direct master R1) |
| S0 (admin) | ✓ | ✓ | ✓ | All (via BROADCAST), M0 (ESCALATE), all (PROPAGATE) |

### Why Topology = Security

1. **No routing configuration**: You never configure "S0 can talk to S2". The topology determines it: S0 → R1 → M0 → S2. Each hop enforces its own ACL.

2. **Per-hop authorization**: Each master independently checks permissions. Even if S0 sends a PROPAGATE, R1 checks `can_propagate` before forwarding. If R1 denies it, M0 never sees the message.

3. **No lateral movement**: A satellite cannot directly message a sibling. ESCALATE goes up, BROADCAST goes down, PROPAGATE goes everywhere. There is no "send to peer" primitive (INTERCOM uses RSA encryption but still routes through the topology).

4. **Relay isolation**: A relay node (R1) enforces permissions on both sides independently. R1 as a master checks S0's permissions. R1 as a satellite has its own permissions checked by M0. Compromising R1's satellite credentials doesn't grant R1's downstream satellites any extra access.

---

## Message Type Behavior Matrix

Complete matrix showing how each message type behaves at each topology position:

### At a Master Node (receiving from a downstream satellite)

| Type | Local action | Forward upstream? | Forward to other satellites? |
|------|-------------|-------------------|------------------------------|
| BUS | Inject into agent bus | No | No (agent decides via response routing) |
| SHARED_BUS | Fire `shared_bus_callback` | No | No |
| ESCALATE | Unpack + handle inner + fire callback | Yes (relay) | No |
| QUERY (request) | Try local agent, respond if possible | Yes (if no local answer) | No |
| PROPAGATE | Unpack + handle inner + fire callback | Yes (relay) | Yes (all except sender) |
| CASCADE (request) | Try local agent, respond + forward | Yes (relay) | Yes (all except sender) |
| BROADCAST | Unpack + handle inner + fire callback | No | Yes (all except sender) |
| QUERY (response) | Route toward originator | N/A | Yes (toward originator) |
| CASCADE (response) | Route toward originator (+ disambiguation) | N/A | Yes (toward originator) |
| BINARY | Dispatch by `bin_type` | No | No |
| INTERCOM | Decrypt + dispatch inner | No | No |

### At a Satellite Node (receiving from upstream master)

| Type | Local action | Forward downstream? |
|------|-------------|---------------------|
| BUS | Emit on internal OVOS bus | No |
| BROADCAST | Handle inner + emit `hive.send.downstream` | Yes (if also a master) |
| PROPAGATE | Handle inner (PING/INTERCOM) + emit `hive.send.downstream` | Yes (if also a master) |
| QUERY (response) | Emit inner BUS on internal bus | No |
| CASCADE (response) | Emit inner BUS on internal bus | No |
| QUERY (request) | Forward downstream via `hive.send.downstream` | Yes (if also a master) |
| CASCADE (request) | Forward downstream via `hive.send.downstream` | Yes (if also a master) |
| INTERCOM | Decrypt + dispatch inner | No |
| ESCALATE, SHARED_BUS | Illegal — logged as warning | No |

### At a Relay Node (dual-role: satellite + master)

A relay is both a satellite (upstream side) and a master (downstream side) sharing one bus. Messages arriving from upstream are handled by `HiveMindSlaveProtocol`; messages from downstream are handled by `HiveMindListenerProtocol`. The shared bus bridges both:

```
Upstream master ←→ [HiveMindSlaveProtocol] ←→ shared bus ←→ [HiveMindListenerProtocol] ←→ Downstream satellites
```

Key relay-specific behaviors:
- `escalate_to_master()` / `query_to_master()` / `cascade_to_master()`: forward upstream via `_upstream_hm`
- `propagate_to_master()`: forward upstream (for PROPAGATE/CASCADE flood)
- `broadcast_from_master()` / `propagate_from_master()` / `query_from_master()` / `cascade_from_master()`: forward downstream to `self.clients`
- `bind_upstream()`: registers all from_master handlers on the satellite's shim

---

## Information Flow Invariants

These properties hold for ALL topologies and ALL message types:

1. **BUS messages are never relayed by protocol.** A satellite's utterance is consumed by its direct master's agent. If the agent can't handle it, escalation is an *agent* decision (e.g., OVOS pipeline plugin), not a protocol decision.

2. **ESCALATE and QUERY only go upstream.** A satellite's ESCALATE never reaches its siblings. A master's `handle_escalate_message` never sends the message to other satellites.

3. **BROADCAST only goes downstream.** Only admin clients can send BROADCAST. The master forwards it to all satellites, never upstream.

4. **PROPAGATE and CASCADE go everywhere.** They are forwarded to all peers (both downstream satellites and upstream masters). Each hop enforces `can_propagate` independently.

5. **Responses route toward the originator.** QUERY/CASCADE responses follow the reverse path back to `originator_peer`. If the originator is a direct client, it's sent directly. Otherwise, it's forwarded to all downstream clients (the correct one will relay it further).

6. **Permissions are enforced per-hop.** Each master independently checks `can_escalate`, `can_propagate`, `is_admin` for its own connected clients. There is no global permission — topology position and local ACL are the only factors.

7. **Encryption is per-link.** Each connection has its own crypto key negotiated via handshake. A relay decrypts from upstream, processes, and re-encrypts for downstream. There is no end-to-end encryption through relays (except INTERCOM, which uses RSA).
