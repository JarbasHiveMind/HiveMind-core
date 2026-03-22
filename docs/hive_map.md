# Hive Map - HiveMind Core

The Hive Map represents the network topology of a HiveMind ecosystem.

## Node Types
A HiveMind network consists of several types of nodes, each with a specific role.
Source: `HiveMindNodeType` — `hivemind_core/protocol.py:64`

- **MIND (Master)**: The central hub that provides AI and coordination capabilities. It is typically the top-level node in a network.
- **SATELLITE (Slave)**: A secondary node that connects to a MIND and performs specific tasks (e.g., audio capture, device control).
- **TERMINAL**: A user-facing endpoint that connects to a MIND for interaction but does not itself accept connections.
- **BRIDGE**: Connects an external service (e.g., Matrix, Mattermost) to the Hive.
- **FAKE-MIND (Fakecroft)**: A node that emulates the behavior of a MIND but uses a different underlying AI stack.

## Network Hierarchy
HiveMind supports hierarchical structures, where one MIND can connect to another.
Source: `HiveMindNodeType.MASTER_MIND` — `hivemind_core/protocol.py:61`

### Master and Slave Nodes
- **Master Node**: The node that listens for connections and provides services.
- **Slave Node**: The node that initiates a connection to a Master.
Source: `HiveMindListenerProtocol.handle_message` — `hivemind_core/protocol.py:255`

### Multi-Hub Setup
A Hub can act as a Slave to another Hub, enabling large-scale, distributed smart environments.
- **Escalation**: A Slave sends a message upwards to its Master.
  Source: `HiveMindListenerProtocol.handle_escalate_message` — `hivemind_core/protocol.py:521`
- **Propagation**: A Master forwards a message downwards to all its Slaves.
  Source: `HiveMindListenerProtocol.handle_propagate_message` — `hivemind_core/protocol.py:483`

## Topology Visualization
In a typical HiveMind setup:
1. **MIND** (Central Hub)
   - **SATELLITE** (Kitchen Speaker)
   - **TERMINAL** (Smartphone App)
   - **BRIDGE** (Home Assistant)
   - **MIND** (Secondary Hub - Office)
     - **SATELLITE** (Office Speaker)
