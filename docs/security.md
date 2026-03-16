# Security and Encryption

HiveMind prioritizes secure communication between the Mind and its satellites, using the `poorman_handshake` library as its cryptographic foundation.

## Handshake and Key Exchange

HiveMind uses the `poorman_handshake` protocol for initial authentication and session key establishment, managed by the `HiveMindClientConnection` in `hivemind_core.protocol`.

1. **Identity**: Every client has an `Access Key` and a `Password` stored in `hivemind_core.database.HiveMindDatabase`.
2. **Session Key**: During connection, a temporary AES-256-GCM session key is derived using PBKDF2 via `poorman_handshake.PasswordHandShake` or `poorman_handshake.HandShake`.
3. **Encryption**: All subsequent traffic is encrypted using this session key.

## Encryption Standards

- **AES-256-GCM**: Used for transport layer encryption. GCM (Galois/Counter Mode) provides both confidentiality and data integrity (AEAD).
- **PBKDF2**: Used for deriving keys from passwords, ensuring resistance to brute-force attacks.
- **PGP (Optional)**: Used for `INTERCOM` messages, allowing end-to-end encrypted secret messages between nodes that the Mind itself cannot decrypt.

## Permissions and Access Control

The Mind enforces strict access control through the `HiveMindDatabase` and `HiveMindClientConnection`:
- **Message Blacklisting**: Managed by `HiveMindDatabase.blacklist_msg` and checked during routing in `HiveMindClientConnection.send`.
- **Skill/Intent Blacklisting**: Restrict which AI skills a specific satellite can trigger via `HiveMindDatabase.blacklist_skill` and `blacklist_intent`.
- **Node-Level Isolation**: Clients only receive messages intended for them or broadcasted to their permission level, as defined by `HiveMindNodeType` in `hivemind_core.protocol`.
