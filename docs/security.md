# Security - HiveMind Core

Security is a foundational pillar of HiveMind Core, combining strong encryption with robust authorization policies.

## Encryption
HiveMind Core supports both symmetric and asymmetric encryption to protect message contents.

### Symmetric Encryption
Once a session key is established via the handshake, all subsequent messages are encrypted using symmetric ciphers.
- **Supported Ciphers**: `AES-GCM`, `CHACHA20-POLY1305`.
- **Encryption Step**: Payloads are serialized and encrypted before transmission.
- **Decryption Step**: Received payloads are decrypted using the stored `crypto_key`.
Source: `HiveMindClientConnection.send` — `hivemind_core/protocol.py:126`
Source: `HiveMindClientConnection.decode` — `hivemind_core/protocol.py:155`

### Asymmetric Encryption
Used for initial handshake and `INTERCOM` messages between nodes that may not share a session key.
- **RSA**: Used for secure key exchange and payload decryption in intercom messages.
Source: `HiveMindListenerProtocol.handle_intercom_message` — `hivemind_core/protocol.py:560`

## Authorization
HiveMind enforces fine-grained authorization policies per client.

### Permission Blacklists
Each client connection maintains blacklists for message types, skills, and intents.
- **Message Blacklist**: Prevents specific `ovos` message types from being sent to the client.
- **Skill Blacklist**: Prevents the client from triggering specific skills.
- **Intent Blacklist**: Prevents the client from triggering specific intents.
Source: `HiveMindClientConnection.send` — `hivemind_core/protocol.py:114`
Source: `HiveMindListenerProtocol._update_blacklist` — `hivemind_core/protocol.py:616`

### Role-Based Access
- **Admin**: Only administrators can perform privileged actions, such as broadcasting messages or accessing the "default" session.
- **Nodes**: Standard clients with limited permissions based on their role (`TERMINAL`, `SATELLITE`, etc.).
Source: `HiveMindListenerProtocol.handle_broadcast_message` — `hivemind_core/protocol.py:444`
Source: `HiveMindListenerProtocol.handle_bus_message` — `hivemind_core/protocol.py:382`

## Secure Message Injection
When a client injects a message into the internal agent bus, it must pass an authorization check.
Source: `HiveMindClientConnection.authorize` — `hivemind_core/protocol.py:168`
Source: `HiveMindListenerProtocol.handle_inject_agent_msg` — `hivemind_core/protocol.py:657`
