# Authentication - HiveMind Core

Authentication in HiveMind Core is managed through a central database and a multi-step handshake process.

## Client Registration
Before a satellite can connect, it must be registered in the HiveMind database. This can be done via the `hivemind-core add-client` CLI command.
- **Access Key**: A unique identifier for the client.
- **Password**: Used to derive encryption keys during the handshake.
- **Admin Status**: Determines if the client can perform privileged actions.
Source: `ClientDatabase.add_client` — `hivemind_core/database.py:53`

## Database Abstraction
HiveMind supports multiple database backends via a plugin system. The default is `hivemind-json-db-plugin`.
Source: `ClientDatabase.__init__` — `hivemind_core/database.py:32`

## Session Management
Each client connection is assigned a `Session` object, which tracks the client's state and context.
- **Site ID**: Identifies the physical location or context of the satellite.
- **Session ID**: A unique identifier for the current user interaction.
Source: `HiveMindClientConnection.sess` — `hivemind_core/protocol.py:91`

### Session Synchronization
When a client connects, it sends a `HELLO` message to synchronize its session state with the hub.
Source: `HiveMindListenerProtocol.handle_hello_message` — `hivemind_core/protocol.py:353`

If a client attempts to use the "default" session without being an administrator, the connection is dropped for security.
Source: `HiveMindListenerProtocol.handle_bus_message` — `hivemind_core/protocol.py:382`

## Handshake Process
Modern HiveMind clients use a `HANDSHAKE` message to establish a secure session key.
- **Password Handshake**: Securely derives a key without transmitting the password.
- **RSA Handshake**: Uses asymmetric keys for identity verification.
Source: `HiveMindListenerProtocol.handle_handshake_message` — `hivemind_core/protocol.py:302`
