# Architecture

## HiveMind in One Paragraph

HiveMind is a protocol and mesh: lightweight **satellite** devices connect to a central
**hivemind-core** hub over an authenticated, encrypted connection. The hub authenticates
each satellite against its client database, enforces per-client permissions through a
policy chain, then routes `HiveMessage` payloads between the satellite and the configured
AI agent backend. Hubs can themselves connect upstream to other hubs (**relay/nested**
topologies), creating scalable multi-tier smart environments.

---

## Message Flow

```
Satellite
   |
   |  HiveMessage (encrypted, authenticated)
   v
NetworkProtocol            ← transport plugin (WebSocket, HTTP, …)
   |
HiveMindListenerProtocol   ← core router (hivemind_core/protocol.py)
   |
   +-- Auth / Handshake
   |
   +-- PolicyChain.review()   ← MessageTypeACLPolicy (always first)
   |                          ← configured plugins (OVOSAgentPolicy, …)
   |
   +-- AgentProtocol          ← agent plugin (OVOS bus, Persona/LLM, …)
   |
   +-- BinaryDataHandlerProtocol  (optional, for audio/image/file payloads)
```

An inbound `HiveMessage` is decrypted and parsed by `NetworkProtocol`, handed to
`HiveMindListenerProtocol`, which runs the policy chain. If admitted, the inner `Message`
payload is forwarded to the `AgentProtocol` (or the binary handler for `BINARY` type
messages). Responses from the agent travel back through the same path.

---

## HiveMessage Types

| Type | Direction | Purpose |
|---|---|---|
| `HANDSHAKE` | bidirectional | Cipher/key negotiation on connect |
| `HELLO` | hub → satellite | Hub identity announcement |
| `BUS` | bidirectional | Wraps an OVOS `Message`; the most common type |
| `SHARED_BUS` | hub → satellite | Hub-bus event pushed to satellite |
| `BROADCAST` | satellite → hub | Deliver to all connected satellites |
| `PROPAGATE` | satellite → hub | Forward upstream to parent hub |
| `ESCALATE` | satellite → hub | Forward up the relay chain |
| `PING` | bidirectional | Keepalive |
| `QUERY` | satellite → hub | Natural-language query; hub streams answer chunks |
| `CASCADE` | hub → satellite(s) | Scatter/gather: distributes a query across children |
| `INTERCOM` | bidirectional | Signed/encrypted end-to-end peer message |
| `BINARY` | bidirectional | Raw bytes (audio, image, file) |

### QUERY / CASCADE streaming

A `QUERY` message triggers `AgentProtocol.natural_language_query(utterance, lang)`, a
generator that yields string answer chunks followed by a final `None` sentinel.
Each chunk is forwarded to the satellite as it arrives. A `hive.query.complete` control
message is sent when the generator exhausts. If the agent yields `None` immediately (no
answer), the hub escalates the query upstream.

`CASCADE` scatters the query across child nodes and gathers their streamed responses.

---

## Plugin Types

hivemind-core is assembled from four plugin types managed by
[hivemind-plugin-manager](https://github.com/JarbasHiveMind/hivemind-plugin-manager):

| Plugin type | Entry-point group | Default | Configures |
|---|---|---|---|
| **Database** | `hivemind.database` | `hivemind-sqlite-db-plugin` | Where client credentials are stored |
| **Network** | `hivemind.network.protocol` | `hivemind-websocket-plugin` | How HiveMessages are transported |
| **Agent** | `hivemind.agent.protocol` | `hivemind-ovos-agent-plugin` | Who handles the message payload |
| **Binary** | `hivemind.binary.protocol` | none (no-op stub) | Server-side STT/TTS/image processing |

A fifth type, **Policy** (`hivemind.policy`), provides admission-control plugins loaded
into the policy chain (see [Policy Chain](policy.md)).

---

## Policy Chain

Every `BUS` (and `BINARY`) message crosses the policy admission chain before reaching the
agent:

1. `MessageTypeACLPolicy` — always first; enforces the per-client `allowed_types`
   whitelist. Deny-by-default: an empty whitelist blocks everything.
2. Configured plugins in `policy.chain` (e.g. `OVOSAgentPolicy` for skill/intent
   blacklists, custom quota or rate-limit plugins).

The chain is fail-closed: any exception in a policy becomes a deny. See [policy.md](policy.md)
for the full specification.

---

## Hub-to-Hub Relay (Nested Topology)

A hub can act as a satellite to an upstream hub. In this role it is a **relay node**:
it holds its own client database for its downstream satellites and forwards messages
upstream when needed. This creates hierarchical topologies where a local hub aggregates
several satellites and delegates to a central hub.

```
Central Hub
   ├── Local Hub A  (also acts as a satellite to Central Hub)
   │     ├── Satellite 1
   │     └── Satellite 2
   └── Local Hub B
         └── Satellite 3
```

---

## Horizontal Scaling Status

A single `HiveMindListenerProtocol` instance is currently the authoritative runtime for
one hub process. The listener keeps live connection state in memory (`clients`,
`hive_mapper`, pending cascade collectors, trusted public keys, query callbacks, and the
agent bus binding). Running two pods behind the same load balancer is therefore safe only
with sticky websocket routing and an external database; it is not yet active-active
sharding.

Before HiveMind can scale one logical hub across several listener pods, these pieces need
to move out of process-local memory:

- **Client/session registry**: live peers, session ids, node type, capabilities, and
  disconnect events need a shared registry or a transport backplane.
- **Routing map**: `HiveMapper` routes must be shared so any pod can find the pod that
  owns a target peer.
- **QUERY/CASCADE collectors**: pending query ids and streamed answer chunks need a
  shared collector or deterministic ownership.
- **Inter-pod delivery**: messages for a client connected to another pod need a pub/sub
  backplane instead of direct in-process method calls.
- **Admission metrics**: policy timing, quota timing, bus emit timing, and agent response
  timing should be recorded separately so operators can see which stage is saturated.

Until those pieces exist, scale by sharding at the hub level: run multiple independent
hubs, keep websocket stickiness for each hub, and use relay/nested topology for larger
fleets.

### Load-test signal

Recent production-style WSS benchmarks with many independent client identities showed a
consistent pattern: one logical hub can complete concurrent direct WSS requests, but high
fan-in increases tail latency inside the listener before OVOS runtime CPU becomes the only
pressure point.

That pattern means adding OVOS replicas alone does not solve one-hub concurrency. The
first pressure point is the websocket/listener process: handshake admission, message
decode/logging, policy review, and agent-bus injection all pass through one process-local
router. Runtime replicas help once messages leave the listener, but the listener must
first drain inbound clients quickly enough.

The control plane has its own burst cost: provisioning hundreds of disposable clients and
credential secrets took minutes. Large launches should pre-provision client identities or
batch onboarding separately from runtime WSS capacity tests.

Near-term mitigations:

- keep per-message and per-disconnect logs at debug level on hot paths;
- use direct database lookup for API-key admission instead of full database sync on every
  websocket open;
- benchmark with independent client identities when measuring user concurrency;
- shard load across more logical hubs when interactive latency matters.

Active-active listener scale needs a larger change: a shared connection/session registry,
cross-listener message delivery, and deterministic ownership for query/cascade collectors.
Without that, multiple listener pods behind one service can only safely work as sticky
websocket replicas, not as a true shared hub.

---

## Identity and Encryption

Each hub has a `NodeIdentity` (stored by `hivemind-bus-client`). Satellites and hubs
negotiate a session cipher during HANDSHAKE. Supported ciphers (order of preference
in config): `CHACHA20-POLY1305`, `AES-GCM`. Supported encodings: `JSON-B64`,
`JSON-URLSAFE-B64`, `JSON-B91`, `JSON-Z85B`, `JSON-Z85P`, `JSON-B32`, `JSON-HEX`.

`INTERCOM` messages add a second layer: signed and end-to-end encrypted between the
originating and target peers, opaque to intermediate relay nodes.

---

## Discovery

Satellites discover the hivemind-core server via:

- **mDNS / zeroconf** (default) — requires the optional `hivemind-presence` package.
- **UPnP/SSDP** — optional, provided by `hivemind-presence` (`upnp: true`).
- Manual — provide host/port directly in the satellite's configuration.
