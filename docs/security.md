# Security and Encryption

HiveMind Core secures communication between the server and its satellites with the `poorman_handshake` library as its cryptographic foundation.

## Handshake and Key Exchange

HiveMind Core uses the `poorman_handshake` protocol for initial authentication and session key setup, managed by `HiveMindClientConnection` in `hivemind_core.protocol`.

1. **Identity**: every client has an `Access Key` and a `Password` stored through `hivemind_core.database.ClientDatabase`.
2. **Session Key**: during connection, the server derives a temporary AES-256-GCM session key with PBKDF2, using `poorman_handshake.PasswordHandShake` or `poorman_handshake.HandShake`.
3. **Encryption**: this session key encrypts all later traffic.

## Encryption Standards

- **AES-256-GCM**: used for transport layer encryption. GCM (Galois/Counter Mode) provides both confidentiality and data integrity (AEAD).
- **PBKDF2**: used for deriving keys from passwords, resisting brute-force attacks.
- **PGP (optional)**: used for `INTERCOM` messages, so nodes can exchange end-to-end encrypted secret messages that the server itself cannot decrypt.

## Permissions and Access Control

The server enforces access control through `ClientDatabase` and `HiveMindClientConnection`:

- **Message whitelist**: `MessageTypeACLPolicy` checks each client's `allowed_types` whitelist during routing. See [Policy Admission Chain](policy.md).
- **Skill/intent blacklisting**: restrict which AI skills a specific satellite can trigger with `hivemind-core blacklist-skill` and `blacklist-intent` (`hivemind_core.scripts`).
- **Node-level isolation**: clients only receive messages meant for them, or broadcast to their permission level, as defined by `HiveMindNodeType` in `hivemind_core.protocol`.

---
[← Installation](installation.md) · [Home](index.md) · [Protocol →](protocol.md)
