# HiveMind Architecture

HiveMind is a decentralized, mesh-networking framework designed to connect lightweight AI satellite devices to a central AI hub.

## Core Components

### 1. The Mind (Hub)
The "Mind" (implemented in `hivemind-core`) is the central server.
- **Service**: Managed by `hivemind_core.service.HiveMindService`.
- **Logic**: Handles incoming connections, authentication, and routing in `hivemind_core.protocol.HiveMindClientConnection`.
- **Permissions**: Enforces per-client blacklists for skills and intents, managed via `hivemind_core.database.HiveMindDatabase`.

### 2. Satellites (Terminals)
Satellites are end-user devices.
- **Client Implementation**: Typically uses `hivemind_bus_client.client.HiveMessageBusClient` from the `hivemind-websocket-client` repo.
- **Node Types**: Defined in `hivemind_core.protocol.HiveMindNodeType` (TERMINAL, MASTER, SLAVE, BRIDGE).

### 3. Bridges
Bridges link external services (Matrix, Mattermost, DeltaChat) to the HiveMind. They translate external protocol messages into HiveMind bus messages and vice-versa.

### 4. Master and Slave Minds (Nested Hive)
HiveMind supports hierarchical setups. A "Slave Mind" connects upstream to a "Master Mind" as a satellite, while simultaneously accepting its own downstream satellite connections. This is enabled by the `MASTER` and `SLAVE` node types in `hivemind_core.protocol.HiveMindNodeType`.

## Message Flow

1. **Connection**: A satellite connects via a Network Protocol plugin (instantiated via `hivemind_plugin_manager.NetworkProtocolFactory`).
2. **Handshake**: The `poorman_handshake` library performs a cryptographic key exchange.
   - **Symmetric**: `poorman_handshake.PasswordHandShake`
   - **Asymmetric**: `poorman_handshake.HandShake`
3. **Routing**:
   - **Upstream**: Satellite sends a `HiveMessage` -> `HiveMindClientConnection.send` handles delivery -> Mind validates permissions -> Mind forwards to Agent (defined by `hivemind_plugin_manager.protocols.AgentProtocol`).
   - **Downstream**: Agent emits a response -> `HiveMindService` identifies the target satellite -> Mind forwards response.
