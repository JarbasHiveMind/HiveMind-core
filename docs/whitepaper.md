# HiveMind: Topology-Driven Security and Semantic Routing for Decentralized AI Agent Networks

**Version 1.0 — March 2026**
**Author:** JarbasAI (jarbasai@mailfence.com)
**Project:** https://github.com/JarbasHiveMind

---

## Abstract

HiveMind is an open-source protocol for connecting distributed AI agents in hierarchical relay networks. It introduces three design principles not found together in existing distributed systems: **topology-as-policy security**, where the network structure itself determines access control without separate configuration; **semantic message-type routing**, where messages declare their routing intent (escalate, propagate, query, broadcast) rather than specifying destination addresses; and **asymmetric directional trust**, where upstream requests are gated before reaching the agent, and downstream responses are unconditional — hivemind-core decides what to send and the satellite executes it without question.

Access control is split across two layers. **Hivemind-core** enforces both HiveMessage type permissions (ESCALATE, PROPAGATE, BUS, etc.) and a per-satellite BUS payload `message_type` whitelist — payloads not in the whitelist are silently dropped before the agent is ever invoked. The **agent protocol** (agent backend) enforces intent and skill blacklists using its own NLP layer on payloads that passed the first layer. HiveMind stores all three permission sets in its database; the agent protocol reads and applies the intent/skill subset.

The BUS message type — the primary carrier of agent interaction — is bidirectional: a satellite sends an agent event upstream (e.g., a user utterance), and hivemind-core's agent sends a response event downstream (e.g., a speak command). Both directions use BUS. HiveMind delivers BUS payloads to the agent without inspecting them; the agent decides what to allow and how to respond.

This paper presents the protocol design, compares it to existing approaches (MQTT, XMPP, libp2p, Matrix), and demonstrates that the combination of topological security, intent-based routing, and directional trust eliminates entire categories of configuration complexity while maintaining strong isolation guarantees between untrusted edge devices.

---

## 1. Introduction

### 1.1 Problem

Deploying AI agents across multiple devices — voice assistants, embedded sensors, mobile clients — creates a distributed system with familiar challenges: routing, authentication, authorization, and discovery. Existing solutions force a choice between simplicity and expressiveness:

- **Centralized brokers** (MQTT, RabbitMQ) are simple but create single points of failure and require per-topic ACL configuration that grows with the number of devices.
- **Peer-to-peer networks** (libp2p, Tor) are resilient but add complexity (DHT routing, NAT traversal) that is unnecessary when devices have a natural authority hierarchy.
- **Federated protocols** (Matrix, XMPP) balance these concerns but require per-server policy configuration and have complex identity management.

None of these approaches exploit a property common to AI agent deployments: **devices have an inherent hierarchical relationship**. A bedroom voice satellite delegates to a home server, which may delegate to a cloud service. This hierarchy is not just a deployment detail — it IS the security policy.

### 1.2 Contribution

HiveMind makes four contributions:

1. **Topology-as-policy**: Access control is determined entirely by a node's position in the network tree and three boolean permission flags. No routing tables, no ACL files, no policy configuration.

2. **Semantic message-type routing**: Messages carry their routing intent as a first-class field. The protocol defines seven routing behaviors (BUS, ESCALATE, PROPAGATE, BROADCAST, QUERY, CASCADE, INTERCOM) that cover all distributed messaging patterns. No destination addressing is needed.

3. **Asymmetric directional trust**: Upstream requests pass through two independent gates. Hivemind-core enforces HiveMessage type permissions and a BUS payload `message_type` whitelist — payloads not in the whitelist are silently dropped, never reaching the agent protocol. The agent protocol then enforces intent and skill blacklists on payloads that passed. Downstream responses are unconditional — hivemind-core decides what to send and the satellite executes without evaluation.

4. **Emergent relay behavior**: A relay node is simply a satellite and a hivemind-core node sharing one event bus. No relay-specific code exists. Multi-hop relay chains of arbitrary depth work without additional implementation.

---

## 2. Architecture

### 2.1 Network Model

A HiveMind network is a directed tree where edges represent persistent connections between nodes. Each node occupies exactly one of three roles:

| Role | Description |
|------|-------------|
| **Master** (hivemind-core) | Accepts connections from satellites. Loads a agent protocol (agent) and delegates all AI processing to it. Enforces per-client transport permissions. Stores per-satellite ACL data for the agent. |
| **Satellite** | Connects to exactly one hivemind-core node. Captures user I/O (microphone, display) and delegates AI processing upstream. |
| **Relay** | Simultaneously a satellite (connected upstream) and a hivemind-core node (accepting downstream connections), sharing one agent bus. |

```
         M0 (root master)
         ├── R1 (relay)
         │   ├── S0 (satellite)
         │   └── S1 (satellite)
         ├── R2 (relay)
         │   └── R3 (nested relay)
         │       ├── S2
         │       └── S3
         └── S4 (direct satellite)
```

Connections are persistent WebSocket (default port 5678) or HTTP REST (port 5679) channels. The protocol is transport-agnostic; any bidirectional channel suffices.

### 2.2 Message Structure

Every communication is a `HiveMessage` with the following fields:

| Field | Type | Purpose |
|-------|------|---------|
| `msg_type` | enum | Routing intent — determines how the message traverses the network |
| `payload` | Message, HiveMessage, dict, or bytes | Content carried by the message |
| `route` | List of hops | Hop-by-hop path record: `[{"source": peer, "targets": [peers]}]` |
| `source_peer` | string | Peer ID of the last node to forward this message |
| `target_peers` | list | Intended recipients (set per-hop) |
| `metadata` | dict | Correlation data (query IDs, response flags) |

The `msg_type` field is the central design element. It replaces destination addressing entirely.

---

## 3. Semantic Message Types

HiveMind defines three categories of message types based on their routing behavior. All message types operate within the directional trust model: upstream flows are requests subject to per-hop authorization; downstream flows are commands that satellites execute without question.

### 3.1 Payload Messages — Consumed Locally

Payload messages are delivered to the receiving node's handler and consumed. They are **never forwarded** by the protocol layer.

| Type | Direction | Purpose |
|------|-----------|---------|
| **BUS** | bidirectional | Carries an agent protocol event. Satellite→hivemind-core: a request (e.g., user utterance), gated by transport ACL then agent-level ACL. Hivemind-core→satellite: a command (e.g., speak response), unconditional. |
| **INTERCOM** | any → any | End-to-end RSA-encrypted peer-to-peer message. Routed through topology but only readable by the target. |
| **BINARY** | bidirectional | Raw binary data (audio, images, files) with a sub-type indicating handling. |

**BUS is the primary interaction primitive.** It carries events on the agent's internal messagebus — the event system that acts as the agent's nervous system, connecting skills, PHAL plugins, speech components, and other subsystems. A complete interaction uses two BUS messages: the satellite sends an upstream BUS event (e.g., `recognizer_loop:utterance`), hivemind-core applies its ACL gates and passes it to the agent protocol, which processes it and emits a response event (e.g., `speak`). Hivemind-core delivers that response downstream; the satellite executes it unconditionally.

HiveMind does not inspect or interpret BUS payloads — it treats them as opaque event envelopes. The agent's internal bus is arbitrary: any event-driven protocol can be used, with any message types the deployment defines.

**Default payload: OVOS MessageBus events.** All first-party HiveMind satellite implementations use a subset of OpenVoiceOS MessageBus event types as BUS payloads by default. This is a deliberate design choice: by speaking the same event language as OVOS, satellites transparently interoperate with PHAL plugins, TTS/STT services, skill handlers, and every other OVOS component — without any satellite-aware code in those components. The satellite appears to the OVOS agent as just another local event source. Nothing in the HiveMind protocol requires OVOS events; this is a practical default, not a protocol constraint.

**Escalation is agent-level, not protocol-level.** If a agent protocol cannot handle an upstream BUS request, it may choose to escalate — forwarding the request as an ESCALATE or QUERY to the next hivemind-core node in the chain. This is a agent protocol decision; the protocol does not automatically escalate BUS messages.

### 3.2 Transport Messages — Route and Forward

Transport messages define routing behavior. Each performs two independent operations: handle the inner payload locally, then forward the outer wrapper to the appropriate destinations.

Messages are categorized by their primary direction of flow, which determines their trust semantics:

**Upstream (request) messages** — initiated by satellites, subject to per-hop authorization at every hivemind-core node:

| Type | Stops when | Permission required |
|------|------------|---------------------|
| **ESCALATE** | Reaches root hivemind-core node | `can_escalate` |
| **QUERY** | First node answers, response routes back | `can_escalate` |
| **PROPAGATE** | Reaches every node (including upstream) | `can_propagate` |
| **CASCADE** | All nodes answer, responses collected | `can_propagate` |

**Downstream (command) messages** — initiated by hivemind-core, satellites comply unconditionally:

| Type | Stops when | Permission required |
|------|------------|---------------------|
| **BROADCAST** | Reaches all leaves | `is_admin` on sender |

**ESCALATE** climbs the authority chain. A satellite's ESCALATE never reaches sibling satellites — only hivemind-core chain above it. Each hivemind-core node in the chain independently decides whether to honor the request or deny it.

**BROADCAST** flows downstream from an admin node to all connected satellites. Satellites receiving a BROADCAST execute the payload without negotiation — it is a directive, not a proposal.

**PROPAGATE** floods in all directions, including upstream. Requires `can_propagate` permission. Each hivemind-core node can deny this at any hop.

**QUERY** climbs upstream until a node's AI agent can answer, then the response routes back downstream. First answer wins. The satellite receives the best available answer without knowing which node produced it. Each upstream hivemind-core node independently decides whether to attempt an answer or pass the query further up.

**CASCADE** floods the entire network and collects responses from all nodes. The originating node selects the best answer via `cascade_select_callback`. This aggregates knowledge from the entire hive — satellites can learn from every agent in the network through a single request, but each hivemind-core node still controls whether its segment participates.

### 3.3 Discovery Messages

| Type | Carrier | Purpose |
|------|---------|---------|
| **PING** | Inside PROPAGATE | Flood-based network discovery. Every node responds with its own PING (same `flood_id`). Route metadata builds the topology graph. |
| **RENDEZVOUS** | HTTP (standalone plugin) | Async store-and-forward dead drop. Sender deposits an INTERCOM payload keyed by recipient pubkey; recipient retrieves later by proving pubkey ownership. Enables nodes from non-simultaneously-connected hives to communicate via a shared rendezvous point. |

PING messages are always carried inside a PROPAGATE wrapper, inheriting its flood routing. Each node that receives a PING responds with its own PING containing the same `flood_id` (preventing infinite loops) and its own identity. The `route` field on each responsive PING records the hops it traversed, enabling passive topology construction without a dedicated discovery protocol.

RENDEZVOUS is implemented as a standalone HTTP plugin (`hivemind-rendezvous`), separate from the WebSocket protocol. It requires no persistent HiveMind session — proof of RSA pubkey ownership (a signed timestamp) is sufficient. The rendezvous node stores the INTERCOM payload opaquely (it cannot read the E2E-encrypted content) and deletes it on delivery. Default TTL: 7 days. See §12.4.

---

## 4. Topology-as-Policy Security

### 4.1 The Core Principle

HiveMind's **transport-layer** security policy is fully determined by two factors:

1. **Its position in the topology tree** — which nodes it can reach and through how many hops.
2. **Three boolean permission flags** — `can_escalate`, `can_propagate`, `is_admin`.

No additional transport configuration exists. There are no routing tables, no ACL files at the protocol level.

Agent-level access control — what a satellite may ask the agent protocol to do — is a separate layer implemented by the agent protocol, using per-satellite permission data stored in the HiveMind database. See §5.2.

### 4.2 Per-Hop Authorization (Upstream Only)

Permission checks apply exclusively to **upstream requests**. Each hivemind-core node independently checks the three flags for its directly connected clients before forwarding an upstream message. A request traversing S0 → R2 → R1 → M0 is authorized three times:

1. R2 checks S0's `can_escalate` / `can_propagate`.
2. R1 checks R2's flags.
3. M0 checks R1's flags.

If any hop denies the request, propagation stops at that hop. The satellite receives no indication of where in the chain the denial occurred.

**Downstream messages are not subject to per-hop authorization.** They are filtered (§5) before dispatch, but satellites do not vote on whether to execute them.

### 4.3 Lateral Movement Prevention

A satellite cannot directly message a sibling satellite. There is no "send to peer" primitive. The only paths between satellites are:

- **ESCALATE/QUERY**: Goes upstream to the shared hivemind-core node. Hivemind-core processes it; siblings never see it.
- **PROPAGATE/CASCADE**: Floods through hivemind-core to all peers. Requires `can_propagate` permission.
- **INTERCOM**: RSA-encrypted, routed through topology. Only the target can decrypt, but every relay in the path handles the envelope.

Compromising one satellite grants no access to siblings unless the compromised satellite has `can_propagate` permission.

### 4.4 Permission Flags — Upstream Scope

The three flags control what a satellite may **request** upstream. See §5.5 for the full permission matrix.

| Flag | Controls |
|------|---------|
| `can_escalate` | May send ESCALATE and QUERY upstream |
| `can_propagate` | May send PROPAGATE and CASCADE (floods full hive) |
| `is_admin` | May initiate BROADCAST (downstream command to all leaves) |

### 4.5 Comparison to Traditional ACL

| Aspect | Traditional ACL | Topology-as-Policy |
|--------|----------------|-------------------|
| Configuration | Per-device rules file | None (topology IS the config) |
| Scaling | O(N²) rules for N devices | O(N) connections |
| Audit | Parse rule files | Inspect topology graph |
| Lateral movement | Prevented by explicit deny rules | Prevented by structure (no direct satellite-to-satellite path) |
| Policy change | Edit ACL, redistribute | Restructure topology (move satellite to different hivemind-core node) |
| Error modes | Misconfigured rule allows unintended access | Misconfigured topology creates unintended reachability (visible in topology graph) |

---

## 5. Asymmetric Directional Trust

### 5.1 The Asymmetry

HiveMind treats upstream and downstream flows as fundamentally different relationships, analogous to a military chain of command:

**Upstream (satellite → hivemind-core): requests, gated by ACL.**
A satellite sends a message to hivemind-core as a petition. Hivemind-core checks one question: "is this satellite permitted to ask this?" If yes, the payload is injected into the agent. If no, the request is dropped and the satellite receives nothing. Every hivemind-core node in the relay chain applies its own check independently. The satellite has no recourse and no visibility into where in the chain a denial occurred.

**Downstream (hivemind-core → satellite): commands, executed without question.**
Hivemind-core decides what to send. The satellite executes it. There is no gate on the downstream path — hivemind-core is always authoritative. A satellite that receives a downstream BUS message does not evaluate it; it injects it into its own local agent bus and acts. This is not a vulnerability; it is the design. A satellite that should not receive a particular class of message should not be permitted to ask for it in the first place.

This asymmetry maps exactly to how devices with different capabilities and trust levels should interact. Edge devices have limited context. Hivemind-core nodes have full context of their subtrees and the authority chain above them. Hivemind-core's judgment is final.

### 5.2 Layered Access Control

Access control for upstream BUS requests operates at two independent layers, both enforced before a response is ever produced:

```
Satellite →[hivemind-core: HiveMessage type + BUS payload message_type]→[agent protocol: intent + skill]→ response
```

**Layer 1 — Hivemind-core ACL (flat deny).** Hivemind-core enforces two checks before the payload touches the agent protocol:

1. **HiveMessage type**: Is this satellite permitted to send this HiveMind envelope type (BUS, ESCALATE, PROPAGATE, etc.)?
2. **BUS payload `message_type` whitelist**: Is the `message_type` field of the BUS payload in this satellite's explicit whitelist?

Both checks are hard gates. A payload that fails either check is silently dropped — it never reaches the agent protocol, and the satellite receives no response. There is no error, no fallback, no agent involvement.

**Layer 2 — Agent-level ACL.** Only payloads that pass Layer 1 reach the agent protocol. The agent protocol applies its own access logic using per-satellite permission data stored in the HiveMind database: intent blacklists and skill blacklists. These require agent-specific NLP and processing; they operate on the *meaning* of the request, not its envelope. How to respond to a denied request (silence, error message, generic denial) is entirely the agent protocol's decision.

### 5.2.1 The Three ACL Dimensions

The HiveMind database stores per-satellite permissions along three dimensions. All values are **arbitrary strings** — their semantics are defined by the agent protocol in use.

#### `message_type` — Explicit Whitelist (enforced by hivemind-core)

A list of BUS payload `message_type` values this satellite is permitted to inject. Only listed values pass; anything absent is a flat no-op — the payload is dropped before the agent protocol is invoked.

In OpenVoiceOS deployments, these are OVOS MessageBus event type strings. Different satellite roles warrant different whitelists:

| Satellite role | Typical whitelist | Rationale |
|---|---|---|
| Voice satellite | `recognizer_loop:utterance` | May only submit spoken queries |
| Home assistant bridge | `speak` | May push speech commands directly; never submits utterances |
| Admin satellite | `recognizer_loop:utterance`, `speak`, `mycroft.volume.set`, … | Full access |

A voice satellite that sends `speak` has that payload silently dropped — hivemind-core never forwards it to the agent protocol. A home assistant bridge that sends `recognizer_loop:utterance` is equally blocked. Each role's whitelist is explicit and minimal.

In other agent deployments, `message_type` values might be API method names, RPC identifiers, or any string the agent protocol uses to classify requests. The protocol does not constrain what strings are used or how many there are.

#### `intent` — Blacklist (enforced by agent protocol)

A list of intent identifiers this satellite is **not** permitted to trigger. Intents are resolved by the agent protocol's NLP layer after the message has passed Layer 1. This dimension only applies to agents that have an intent recognition concept; it may be a no-op for agents that do not.

In OpenVoiceOS, an intent is the resolved handler name for an utterance — e.g., `calendar.query.intent`, `shopping.order.intent`. The agent protocol resolves the utterance to an intent, then checks whether that intent is blacklisted for this satellite before executing.

In an LLM deployment, an "intent" might be a free-text description that the LLM matches against, or it might have no direct equivalent.

#### `skill` — Blacklist (enforced by agent protocol)

A list of skill (or module/capability) identifiers this satellite is **not** permitted to trigger. This is coarser than intent-level blocking — blacklisting a skill blocks all intents from that skill without listing them individually.

In OpenVoiceOS, skills are identified by plugin entry point name (e.g., `skill-calendar.openvoiceos`). In an LLM deployment, the equivalent might be a tool namespace or capability group.

Like `intent`, skill blacklisting requires the agent protocol to have a concept of discrete functional units. It may not apply to all agent types.

### 5.2.2 Agent Protocol Contract

Any agent backend loaded by hivemind-core implements the agent protocol interface. A conforming agent protocol implementation MUST:

1. Accept BUS payloads from hivemind-core (Layer 1 has already passed; `message_type` is guaranteed to be in the satellite's whitelist).
2. Read per-satellite `intent` and `skill` blacklists from the HiveMind database and apply them using its own NLP/resolution layer.
3. If the agent protocol has no concept of intents or skills, treat those fields as no-ops without error.
4. Return responses to hivemind-core as BUS payloads for downstream delivery.

The agent protocol does **not** need to re-check `message_type` — that was already enforced by hivemind-core. Conversation state, prompt management, model selection, and response generation are entirely the agent protocol's concern.

### 5.2.3 Interaction Example

Using OpenVoiceOS as the agent protocol, two satellites with different whitelists:

```
Voice satellite (S0) sends BUS: recognizer_loop:utterance ("what time is it?")
  → hivemind-core: BUS permitted; recognizer_loop:utterance in S0's whitelist → pass to agent protocol
  → Agent protocol (OVOS): resolves intent → time.query.intent
  → time.query.intent not in S0's intent blacklist; time skill not in S0's skill blacklist → execute
  → Produces: speak ("it is 3pm")
  → hivemind-core sends BUS downstream to S0
  → S0 executes speak unconditionally
```

Voice satellite attempts to push a speak command directly:

```
Voice satellite (S0) sends BUS: speak ("hello")
  → hivemind-core: speak not in S0's message_type whitelist → flat drop, no-op
  → Agent protocol never invoked
```

Home assistant bridge (H0) pushes a speak command:

```
H0 sends BUS: speak ("dinner is ready")
  → hivemind-core: speak in H0's message_type whitelist → pass to agent protocol
  → Agent protocol receives speak, executes directly (no intent resolution needed)
  → hivemind-core sends BUS: speak downstream
```

Guest satellite blocked at agent level (message_type passes, intent blocked):

```
Guest (G0) sends BUS: recognizer_loop:utterance ("what's on Dad's schedule?")
  → hivemind-core: recognizer_loop:utterance in G0's whitelist → pass to agent protocol
  → Agent protocol resolves intent → calendar.query.intent
  → calendar.query.intent in G0's intent blacklist → deny
  → Agent protocol returns BUS: speak ("I can't help with that") or nothing
```

### 5.3 Information Flow Consequences

**Upstream aggregates knowledge freely (within ACL).** A satellite's QUERY or CASCADE traverses the hive, gathering responses from every reachable agent. A satellite may not know the full topology, but through these mechanisms it benefits from every intelligence above it, subject only to the ACL gates at each hop. Information concentrates upward: masters always know more than satellites.

**Downstream is unconditional at every hop.** Once a hivemind-core node decides to send a downstream message, relay nodes forward it to their satellites without re-checking. The policy decision was made at hivemind-core; relays carry it out.

```
Upstream:   S0 →[HiveMsg type + message_type whitelist]→[intent/skill blacklist]→ R1 → … → M0
                 (hivemind-core, flat deny)               (agent protocol)
Downstream: M0 → R1 → S0   (unconditional at every hop)
```

### 5.4 Why Satellites Cannot Refuse Commands

A satellite has no mechanism to reject a downstream message. This reflects the trust relationship established at connection time:

- The satellite authenticated to hivemind-core and was assigned its permissions.
- Hivemind-core accepted the connection and is responsible for every message it sends downstream.
- If a satellite should not receive a class of message, the correct mechanism is ACL configuration at hivemind-core, not satellite-side refusal logic.

Distributing policy to untrusted edge nodes defeats the architecture. Hivemind-core's authority is unconditional.

### 5.5 Permission Matrix

The three routing flags govern HiveMind transport permissions only. Agent-level access control (intent/skill blacklists, content filters) is a separate layer implemented by the agent using per-satellite data from the HiveMind database.

| Satellite type | `can_escalate` | `can_propagate` | `is_admin` | Upstream routing reach | Downstream behavior |
|----------------|:-:|:-:|:-:|---|---|
| Default | Yes | Yes | No | Hivemind-core chain + full hive via PROPAGATE | Executes all commands |
| Restricted | No | No | No | Direct hivemind-core node only (BUS) | Executes all commands |
| Admin | Yes | Yes | Yes | All nodes; may initiate BROADCAST | Executes all commands; may issue BROADCAST |
| Escalate-only | Yes | No | No | Hivemind-core chain only | Executes all commands |

`is_admin` controls the right to **issue** BROADCAST. It does not affect whether the node executes commands sent to it — all satellites always do.

---

## 6. Relay Architecture

### 6.1 Emergent Relay Behavior

A relay node is a satellite and a hivemind-core node sharing one event bus. When the satellite side receives a PROPAGATE from upstream, it dispatches it locally. Hivemind-core side, registered via `bind_upstream()`, picks up the message and forwards it to downstream clients. No relay-specific protocol code exists.

```
Upstream hivemind-core ←→ [Satellite Protocol] ←→ shared bus ←→ [Master Protocol] ←→ Downstream satellites
```

This design has three consequences:

1. **Arbitrary depth**: Relay chains of any depth work without modification. A 10-level chain behaves identically to a 2-level chain.
2. **No relay configuration**: A node becomes a relay simply by connecting upstream AND accepting downstream connections. No mode switch, no configuration flag.
3. **Unified protocol**: The same `HiveMessage` type and wire format is used at every hop. There is no separate relay protocol.

Relay nodes enforce the directional trust model at both boundaries: they check transport ACL when forwarding upstream requests from their satellites, and forward downstream commands unconditionally to their satellites.

### 6.2 Message Flow Through a Relay

**ESCALATE (upstream request):**
```
S0 → R1_master (authorize: can_escalate?, handle, forward upstream)
   → R1_satellite (sends to M0)
   → M0 (handle)
```

**PROPAGATE (flood — upstream request):**
```
S0 → R1_master (authorize: can_propagate?, handle, forward to other clients + upstream)
   → R1_satellite (sends to M0)
   → M0 (handle, forward to other clients)
```

**BROADCAST (downstream command — unconditional):**
```
M0 → R1_satellite (receives command from upstream hivemind-core node)
   → R1_master (bind_upstream handler forwards to downstream)
   → S0, S1 (receive and execute unconditionally)
```

---

## 7. PING Flood Discovery

### 7.1 Protocol

Network discovery uses a single message type (PING) carried inside PROPAGATE:

1. The initiating hivemind-core node creates a PING with a unique `flood_id` and sends it as PROPAGATE to all connected clients.
2. Each satellite that receives the PING responds with its own PING containing the same `flood_id`, its peer identity, and its site ID.
3. Each hivemind-core node that receives a responsive PING feeds it into a local topology mapper (`HiveMapper`) and forwards it to all other connected peers (standard PROPAGATE behavior).
4. Nodes track seen `flood_id` values to prevent sending duplicate responsive PINGs.

### 7.2 Topology Construction

Each PING message carries a `route` field recording its hop-by-hop path. The `HiveMapper` extracts directed edges from route hops:

```
route: [
    {"source": "S0::abc", "targets": ["R1_master:0.0.0.0"]},
    {"source": "R1_sat::def", "targets": ["M0:0.0.0.0"]}
]
→ edges: S0→R1, R1→M0
```

After a single PING flood, the initiating hivemind-core node has a complete directed graph of all reachable nodes — built passively from route metadata, without a dedicated topology advertisement protocol.

### 7.3 Properties

- **Convergence**: A single flood discovers all reachable nodes. No iterative refinement needed.
- **Consistency**: Every node responds exactly once per `flood_id`. The initiating hivemind-core node receives one PING per reachable node.
- **Passivity**: Topology is inferred from route metadata. No separate link-state advertisements, no routing table exchanges.
- **RTT estimation**: Each PING carries a sender timestamp. The receiver can estimate round-trip time from the difference between sender and local clocks.

---

## 8. Encryption

### 8.1 Per-Link Encryption

Every connection negotiates encryption during the handshake phase. Supported algorithms:

| Cipher | Key Size | Nonce | Tag |
|--------|----------|-------|-----|
| AES-GCM | 128/192/256 bit | 16 bytes | 16 bytes |
| ChaCha20-Poly1305 | 256 bit | 12 bytes | 16 bytes |

Ciphertext is encoded for transport using one of seven encodings (Base64, Base91, Z85, Base32, Hex, or URL-safe Base64), negotiated during the handshake.

### 8.2 Handshake

Two handshake modes are supported:

- **Password-based**: Client and server derive a shared key from a pre-shared password using a challenge-response protocol.
- **RSA key exchange**: Client and server exchange public keys and negotiate a symmetric session key.

### 8.3 End-to-End Encryption (INTERCOM)

INTERCOM messages provide end-to-end encryption using RSA. The sender encrypts with the target's public key. Intermediate relays handle the encrypted envelope without access to the plaintext. This is the only message type that provides confidentiality across relay hops.

---

## 9. LLM and Multi-Agent Deployments

### 9.1 The Transport–Agent Boundary

HiveMind is deliberately a transport protocol, not an AI framework. It does not manage conversation state, prompt templates, context windows, or model selection. These concerns belong to the agent protocol running on each hivemind-core node.

The interface between HiveMind and the agent protocol is exactly one thing: the BUS message. A BUS message arriving from a satellite is handed to the agent protocol for handling. A BUS message returned by the agent protocol is forwarded downstream to the satellite. HiveMind does not interpret the payload — it enforces transport-level permissions and routes the envelope.

This separation is a design feature. By keeping BUS payloads opaque, HiveMind supports any AI backend as an agent protocol: OVOS skill engine, LLM chat completion backend, RAG pipeline, tool-calling agent, or any custom event-driven protocol. Swapping the agent protocol implementation does not affect HiveMind's routing or transport security behavior.

The default first-party satellite implementations use OVOS MessageBus event types as BUS payloads. This choice is intentional: satellites that speak the OVOS event language interoperate transparently with PHAL plugins, TTS/STT services, and skill handlers without those components needing any HiveMind-specific code. The satellite is indistinguishable from a local event source. This is a practical default, not a protocol requirement.

**Hivemind-core as transport firewall and agent protocol host.** `hivemind-core` enforces HiveMind's transport-level ACL (§4), loads the configured agent protocol, stores per-satellite permission data in its database, and provides that data to the plugin on each request. The agent protocol enforces agent-level ACL using the three dimensions defined in §5.2.1. HiveMind controls routing and transport permissions; the agent protocol controls what it acts on.

### 9.2 Session Continuity

Each satellite connection is bound to a `session_id` that persists for the lifetime of the connection. Hivemind-core's agent associates state (conversation history, user preferences, active context) with this session. The protocol does not prescribe how state is stored or propagated — it only guarantees that messages from the same satellite arrive with the same `session_id`.

For multi-turn LLM conversations through relay chains, the agent includes conversation history in the BUS payload's `data` or `context` fields. The relay's agent decides whether to forward the full history upstream or summarize it. This is an agent-level decision that the protocol correctly does not constrain.

### 9.3 Model Hierarchy via Topology

The topology-as-policy model maps directly to tiered LLM deployments:

```
Cloud (GPT-4 class)       ← M0 (root master)
    ├── Home server (Llama 70B)  ← R1 (relay)
    │   ├── Bedroom satellite     ← S0
    │   └── Kitchen satellite     ← S1
    └── Mobile phone (Llama 8B)   ← S2 (direct satellite)
```

In this topology:

- S0's utterance (an upstream request) goes to R1's local model first. If R1's agent can handle it, the response stays local — no data leaves the home network. This is a structural privacy guarantee, not a configuration option.
- If R1's agent cannot handle the request, it escalates to M0 (cloud). The decision to escalate is made by R1's agent, not by the protocol. The protocol only provides the ESCALATE and QUERY mechanisms.
- S2 (mobile) connects directly to the cloud. Its requests always reach the large model. This is a topology decision, not a permission decision.
- When M0 returns a response downstream to S0 via R1, R1 forwards it unconditionally. S0 executes whatever hivemind-core delivers. Access control was enforced at the request boundary — S0 could not have asked for information it is not permitted to receive.

**QUERY enables automatic model fallback.** S0 sends a QUERY (upstream request). R1's local model attempts an answer. If it succeeds, the response routes back immediately and M0 never sees the request. If it fails, the QUERY escalates to M0 automatically. The satellite receives the best available answer without knowing which model produced it, and without being able to request a specific model.

**CASCADE enables ensemble consensus and hive-wide learning.** S0 sends a CASCADE (upstream request). Every agent in the hive responds: R1's local model, M0's cloud model, and any other agent reachable via PROPAGATE routing. The originating node collects all responses and selects the best one via `cascade_select_callback`. A satellite can thus benefit from the entire hive's intelligence through a single request — always learning upward, never selecting which nodes to query.

### 9.4 Agent-to-Agent Communication

INTERCOM provides end-to-end encrypted agent-to-agent messaging. In multi-agent LLM deployments, this enables:

- A personal agent on your phone negotiating with a company agent on a corporate server, with intermediate relays unable to read the conversation.
- A local model requesting specific capabilities from a specialized remote model (code generation, image analysis) without exposing the full conversation to the relay chain.

This addresses an unsolved problem in current LLM agent frameworks: secure cross-organizational agent communication with confidentiality guarantees through untrusted intermediaries.

### 9.5 What HiveMind Does Not Do

HiveMind does not manage prompts, context windows, model selection, token budgets, or tool calling. It does not stream tokens (messages are discrete). It does not enforce response quality or implement ranking between model outputs (the CASCADE callback is an extension point, not a built-in scorer).

These are agent-level concerns. HiveMind provides the secure, routed transport layer beneath them. An LLM agent framework (OVOS pipeline, LangChain, custom code) runs on each hivemind-core node and makes all AI decisions. HiveMind ensures those decisions are enforced across trust boundaries.

---

## 10. Comparison to Existing Systems

### 10.1 MQTT and MQTT-SN

MQTT uses topic-based pub/sub with a centralized broker. MQTT-SN extends this to constrained sensor networks with gateway nodes analogous to HiveMind relays.

**Key differences:** MQTT routes by topic string; HiveMind routes by message intent. MQTT requires per-broker ACL configuration; HiveMind derives access control from topology. MQTT's QoS levels (at-most-once, at-least-once, exactly-once) have no direct analog in HiveMind, which provides best-effort delivery for transport messages and exactly-once semantics for PING discovery.

### 10.2 XMPP Federation

XMPP uses federated servers with server-to-server (S2S) and client-to-server (C2S) protocols. Stanza types (message, presence, iq) define routing behavior.

**Key differences:** XMPP's stanza types are fixed and semantically narrow (chat, presence, query). HiveMind's message types encode richer routing intent (escalate vs. propagate vs. cascade). XMPP requires per-server federation configuration; HiveMind relays are configuration-free. XMPP's Multi-User Chat (MUC) is more complex than HiveMind's BROADCAST for group messaging.

### 10.3 libp2p

libp2p is a modular peer-to-peer networking stack used by IPFS, Filecoin, and Ethereum 2.0. It provides DHT-based routing, NAT traversal, and pluggable transport.

**Key differences:** libp2p is designed for flat peer-to-peer networks; HiveMind is designed for hierarchical authority chains. libp2p requires DHT participation for routing; HiveMind uses topology position. libp2p's complexity (Kademlia DHT, relay protocols, hole punching) is unnecessary when devices have a natural hierarchy. HiveMind's protocol is substantially simpler.

### 10.4 Matrix Federation

Matrix uses federated homeservers with room-based messaging. Servers replicate room state via the federation protocol.

**Key differences:** Matrix uses room-based access control with explicit membership; HiveMind uses topology-based access control with no configuration. Matrix requires a separate server-to-server protocol; HiveMind uses one protocol for all node types. Matrix's Megolm/Olm provides end-to-end encryption by default; HiveMind uses per-link encryption with optional INTERCOM for E2E.

### 10.5 Summary

| Property | MQTT | XMPP | libp2p | Matrix | **HiveMind** |
|----------|:----:|:----:|:------:|:------:|:--------:|
| Topology | Star (broker) | Federated graph | Flat mesh | Federated graph | **Relay tree** |
| Routing | Topic-based | JID-based | DHT | Room-based | **Intent-based** |
| Access control | Broker ACL | Server policy | Crypto identity | Room membership | **Topology position** |
| Relay support | Bridge (configured) | S2S (configured) | Relay protocol | Federation | **Emergent (zero config)** |
| Configuration needed | Per-broker | Per-server | Per-node | Per-homeserver | **Per-connection only** |
| E2E encryption | Optional | Optional | Built-in | Default | Per-link + INTERCOM |
| Discovery | Broker knows all | Service discovery | DHT | Server list | **PING flood** |

---

## 11. Limitations and Future Work

### 11.1 Current Limitations

**Tree topology constraint.** Each satellite connects to exactly one hivemind-core node. This prevents mesh topologies where a satellite could fall back to an alternative hivemind-core node if its primary becomes unavailable. Redundancy requires external mechanisms (load balancer, DNS failover).

**No rate limiting.** A satellite with `can_propagate=True` can flood the network continuously. Per-client bandwidth limits are not enforced at the protocol level.

**Per-link encryption overhead.** Each relay hop requires a decrypt-reencrypt cycle. Deep relay chains (10+ hops) incur cumulative latency. End-to-end encryption (INTERCOM) is available but uses RSA, which is limited to small payloads.

**Route integrity.** The `route` field records hop history but is not cryptographically signed. A malicious relay could forge route data. This affects topology discovery accuracy but not message delivery.

### 11.2 Future Directions

**Mesh extensions.** Allow satellites to maintain standby connections to alternative masters for failover, while preserving the primary authority chain for security policy.

**Stream-level E2E encryption.** Extend INTERCOM from per-message RSA to session-based symmetric encryption (similar to Signal Protocol's Double Ratchet) for efficient E2E encrypted streams.

**Signed routes.** Each node signs its route hop entry, enabling receivers to verify the full path cryptographically. This would make topology discovery tamper-evident.

**Time-based and rate-based ACL.** Extend the three-flag permission model with optional time windows and message rate limits per client.

---

## 12. Privacy and Anonymity Properties

### 12.1 What Each Party Knows

HiveMind has an asymmetric information model. What a node knows about others depends entirely on its position:

| Node type | Knows | Does not know |
|---|---|---|
| Satellite | IP/address of its direct hivemind-core node only | IP, location, identity of any other satellite or upstream node |
| Hivemind-core node | IP and peer ID of every directly connected client | IP/location of clients connected to other nodes |
| Relay | IP and peer ID of its own satellites; peer ID of upstream node | IP of upstream node's satellites or higher nodes |

A satellite connecting to a public hivemind-core node reveals its IP to that node and nothing else. Every other participant in the hive is opaque: their IPs, locations, and identities are unknown.

### 12.2 Leaf-to-Leaf Communication: Two Privacy Tiers

Two satellites in the same hive can communicate through two distinct models with different privacy properties.

#### Group communication via BUS (agent-mediated)

Satellites send BUS messages to a shared agent protocol — via PROPAGATE to flood all subscribers, or through a shared session concept. The agent protocol receives all messages, processes them, and delivers results downstream to each participant individually.

This enables shared chatrooms where the agent is the only node that sees raw content. Each satellite receives only what the agent sends it — translated, filtered, or reformatted for that recipient. Satellites never see each other's raw messages.

A cross-language chatroom: every satellite sends utterances (via ASR or text) as BUS messages. The agent protocol knows each participant's language, translates each message for every other participant, and sends `speak` commands downstream. Each participant hears the conversation in their own language. No satellite knows the language, location, or identity of any other participant — only the agent does.

The agent protocol is the privacy boundary here. It is trusted with content; the satellites are not.

#### Private messaging via INTERCOM (end-to-end)

INTERCOM provides a second tier where even the agent cannot read the content. The sender encrypts directly to the recipient's RSA public key. Relay nodes handle the envelope but cannot decrypt it.

Cross-language private messaging without agent involvement: the **sender** performs ASR and machine translation locally, producing text in a pre-agreed common language. The sender wraps a `speak` command containing the translated text in INTERCOM, encrypted to the recipient's public key. The recipient decrypts and executes the `speak` command — performing TTS locally in their own voice stack. The agent protocol and every relay in the path see only an opaque encrypted envelope. Neither the sender's original language nor the message content is ever visible outside the two endpoints.

This requires two preconditions: both parties must have each other's public keys, and they must agree on a common intermediate language for translation. Both can be bootstrapped via PING (§12.3).

#### Public key discovery via PING

PING flood responses carry each node's peer identity. Extending peer identity to include a public key allows any node to initiate an INTERCOM session with any other discovered node without prior out-of-band contact. A satellite learns the topology and public keys of all reachable peers from a single PING flood, then can open private INTERCOM channels to any of them.

The full pattern: satellites join a shared hivemind-core node (the rendezvous). A PING flood populates public keys. Group conversation flows through the agent via BUS (agent-translated, agent-mediated). Private conversations use INTERCOM with sender-side translation — the agent never sees them. Neither party ever knows the other's IP, location, or native language.

### 12.3 PING Flood: Discovery Utility vs. Privacy Trade-off

PING is both the enabler of the communication patterns in §12.2 and the protocol's primary privacy trade-off.

**As an enabler:** A PING flood gives every satellite a map of the hive — peer IDs, positions, and (if extended) public keys of every reachable node. This is what makes INTERCOM DM initiation possible without prior out-of-band contact, and what makes chatroom participant discovery work.

**As a privacy concern:** The same flood that gives participants their peer list also gives the initiating node — and every relay that handles the responses — a complete directed graph of the hive. Specifically:

- A hivemind-core operator who initiates a PING flood learns the peer IDs and relay positions of every connected satellite. Combined with connection metadata (who authenticated when), this is a full participant roster.
- A satellite with `can_propagate=True` that initiates a PING flood learns the peer IDs of every other node in the hive. Peer IDs are persistent identifiers: they don't carry IPs, but at the relay level they correlate to known connections.
- Relay nodes handling PING responses learn the peer IDs and topology of their subtrees.

**PING does not break INTERCOM content confidentiality** — it reveals that nodes exist and where they sit, not what they are saying. But it does allow an observer with `can_propagate` permission to infer that a communication relationship exists between two peers, and to correlate peer IDs across sessions if peer IDs are stable.

**Mitigation:** Hivemind-core operators can restrict `can_propagate` on satellites, preventing external participants from initiating network enumeration. The operator's own node retains the ability to map its hive. For deployments where participant anonymity within the hive matters, peer IDs should be rotated per session and PING responses should be opt-in rather than automatic — both are protocol extensions not currently defined.

### 12.4 What Relay Operators Can Observe

A relay operator (a node in the path between two communicating parties) can observe:

- **Envelope metadata**: source peer ID, target peer IDs, message type (INTERCOM), message size, and timing. This enables traffic analysis — inferring communication patterns without reading content.
- **Topology**: peer IDs and positions of all nodes in the relay's subtree, via PING.
- **BUS traffic in plaintext**: BUS messages passing through the relay are decrypted at each hop (per-link encryption). An operator controlling a relay node in the chain reads all non-INTERCOM traffic.

INTERCOM is the only message type that provides confidentiality against relay operators.

### 12.4 RENDEZVOUS: Async Dead Drop for Disconnected Hives

The RENDEZVOUS mechanism (implemented in `hivemind-rendezvous`) enables nodes from non-simultaneously-connected hives to exchange INTERCOM messages via a shared intermediary.

**Flow:**
1. Node A deposits an INTERCOM payload at a known rendezvous server, keyed by Node B's RSA public key fingerprint.
2. Node B retrieves its messages at any later time by proving it owns that public key — it signs `pubkey + str(timestamp)` with its private key and submits the signature.  The server verifies the signature and checks the timestamp is within 60 seconds (replay protection).
3. Messages are deleted on delivery (at-most-once semantics).  Default TTL: 7 days.

**Privacy properties of RENDEZVOUS:**

- **The rendezvous node cannot read message content.** Payloads are E2E RSA-encrypted INTERCOM messages; the node stores them opaquely.
- **The rendezvous node knows the recipient's public key fingerprint** (SHA-256 of PEM), not the full key.  It cannot map this to an IP address or identity unless it also participated in a PING flood.
- **The sender's identity is optional.** Anonymous deposits (no depositor proof) are accepted in default mode.  The rendezvous node logs the depositing IP unless rate limiting is configured to discard it.
- **Neither party's IP is revealed to the other.** Nodes communicate only through the rendezvous node; no direct connection is ever established.
- **Proof of key ownership is stateless.** No server-side challenge is stored; a compromised rendezvous node cannot replay challenges to impersonate recipients.

**Threat model note:** The rendezvous node is a trusted infrastructure component in the same sense that any relay is.  An adversary controlling the rendezvous node can observe deposit metadata (timing, size, recipient fingerprint) and could withhold messages.  It cannot forge INTERCOM content or deceive the recipient into accepting messages not encrypted to their key.

### 12.5 Summary of Privacy Properties

| Property | Provided | Notes |
|---|---|---|
| Wire confidentiality | Yes (all traffic) | Per-link AES-GCM or ChaCha20-Poly1305 |
| Content confidentiality from relay operators | INTERCOM only | BUS/BINARY readable at each relay hop; INTERCOM opaque |
| Leaf IP concealment from other leaves | Yes | Satellites never learn peers' IPs |
| Leaf identity concealment (group chat) | Partial | Agent sees all content; other leaves see only their own translated output |
| Leaf identity concealment (INTERCOM DM) | Yes | Sender encrypts to recipient public key; agent and relays see only envelope |
| Content confidentiality from direct hivemind-core | INTERCOM only | Direct node handles BUS in plaintext; cannot decrypt INTERCOM |
| Public key discovery without prior contact | Yes (via PING) | PING responses can carry public keys enabling INTERCOM initiation |
| Topology concealment from privileged nodes | No | PING flood reveals full reachable graph to initiator and relay chain |
| Communication relationship concealment | No | PING and envelope metadata reveal which peers communicate |
| Traffic analysis resistance | No | Timing, size, and peer metadata visible to relay operators |
| Forward secrecy | No | Not defined in current handshake |
| Anonymity from direct hivemind-core | No | IP and credentials revealed at connection |
| Async communication without simultaneous connection | Yes (RENDEZVOUS) | Dead-drop delivery; neither party's IP revealed to the other; rendezvous node sees fingerprint + metadata only |

---

## 13. Conclusion

HiveMind demonstrates that hierarchical AI agent networks can be secured and routed without traditional access control configuration. By encoding routing intent in the message type and deriving access policy from topology position, the protocol eliminates per-device ACL management while providing strong isolation guarantees between untrusted edge devices.

The relay architecture — where relaying emerges from sharing an event bus between a satellite and hivemind-core protocol, with no relay-specific code — shows that protocol composition can replace dedicated relay implementations.

These design choices make HiveMind well-suited for deployments where devices have natural authority relationships (home automation, edge AI, voice assistant networks) and where operational simplicity is valued over the flexibility of full mesh or federated architectures.

---

## References

- HiveMind Core: https://github.com/JarbasHiveMind/HiveMind-core (AGPL-3.0)
- HiveMind Bus Client: https://github.com/JarbasHiveMind/hivemind_websocket_client (Apache-2.0)
- OpenVoiceOS: https://github.com/OpenVoiceOS (voice assistant platform)
- MQTT 5.0 Specification: https://docs.oasis-open.org/mqtt/mqtt/v5.0/mqtt-v5.0.html
- XMPP Core (RFC 6120): https://datatracker.ietf.org/doc/html/rfc6120
- libp2p Specification: https://github.com/libp2p/specs
- Matrix Specification: https://spec.matrix.org/latest/
- AES-GCM (NIST SP 800-38D): https://csrc.nist.gov/publications/detail/sp/800-38d/final
- ChaCha20-Poly1305 (RFC 7539): https://datatracker.ietf.org/doc/html/rfc7539
