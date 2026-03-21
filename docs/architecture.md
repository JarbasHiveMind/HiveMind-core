# Architecture - HiveMind Core

HiveMind Core is built around a modular architecture that separates communication protocols, agent handling, and data management.

## Core Components
The `HiveMindService` class is the main entry point that coordinates all components.
Source: `HiveMindService` — `hivemind_core/service.py:84`

### Protocols
HiveMind separates its functionality into three specialized protocol layers:
1. **Network Protocols**: Handle the physical transport of messages (e.g., WebSockets, HTTP).
   Source: `HiveMindService.run` — `hivemind_core/service.py:192`
2. **Agent Protocols**: Define how HiveMind interacts with an AI "mind" (e.g., OpenVoiceOS).
   Source: `AgentProtocol` — `hivemind_core/protocol.py:173`
3. **Binary Protocols**: Handle specialized binary data streams (e.g., audio, images).
   Source: `BinaryDataHandlerProtocol` — `hivemind_core/protocol.py:174`

### HiveMind Listener Protocol
The `HiveMindListenerProtocol` class implements the logic for processing `HiveMessage` objects. It manages the registry of active clients and coordinates message routing.
Source: `HiveMindListenerProtocol` — `hivemind_core/protocol.py:172`

### Client Connections
Each connected satellite is represented by a `HiveMindClientConnection` object, which stores its session, encryption keys, and permission blacklists.
Source: `HiveMindClientConnection` — `hivemind_core/protocol.py:82`

## Data Flow
1. A **Network Protocol** receives a raw payload and passes it to the `HiveMindListenerProtocol`.
2. The payload is decrypted using the key in the `HiveMindClientConnection`.
   Source: `HiveMindClientConnection.decode` — `hivemind_core/protocol.py:155`
3. The message is validated and processed by `HiveMindListenerProtocol.handle_message`.
   Source: `HiveMindListenerProtocol.handle_message` — `hivemind_core/protocol.py:381`
4. If it's a `BUS` message, it's authorized and forwarded to the **Agent Protocol**.
   Source: `HiveMindListenerProtocol.handle_inject_agent_msg` — `hivemind_core/protocol.py:657`
5. The **Agent Protocol** interacts with the AI backend (e.g., OVOS MessageBus) to fulfill the request.
