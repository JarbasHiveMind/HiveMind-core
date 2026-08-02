# Security and Encryption

HiveMind Core secures communication between the server and its satellites with the `poorman_handshake` library as its cryptographic foundation.

## Handshake and Key Exchange

HiveMind Core uses the `poorman_handshake` protocol for initial authentication and session key setup, managed by `HiveMindClientConnection` in `hivemind_core.protocol`.

1. **Identity**: every client has an `Access Key` and a `Password` stored through `hivemind_core.database.ClientDatabase`.
2. **Session Key**: during connection, the server derives a temporary session key with PBKDF2, using `poorman_handshake.PasswordHandShake` or `poorman_handshake.HandShake`.
3. **Cipher**: the client proposes ciphers and the server picks the first one its `allowed_ciphers` list also holds. The default order prefers `CHACHA20-POLY1305`, then `AES-GCM`.
4. **Encryption**: this session key encrypts all later traffic.
5. **Protocol v3**: a client that supports the Noise handshake (XXpsk2/KKpsk0) gets an authenticated, forward-secret transport instead of the session-key layer.

## Encryption Standards

- **ChaCha20-Poly1305** and **AES-256-GCM**: used for transport layer encryption. Both are AEAD ciphers, so both give confidentiality and data integrity.
- **PBKDF2**: used for deriving keys from passwords, resisting brute-force attacks.
- **RSA**: used for `INTERCOM` messages, so nodes can exchange end-to-end encrypted messages that a relay node cannot read. The server verifies the origin signature and pins the sender's public key on first sighting. While `require_crypto` is true, the server drops an unsigned `INTERCOM` frame instead of relaying it.

## Permissions and Access Control

The server enforces access control through `ClientDatabase` and `HiveMindClientConnection`:

- **Message whitelist**: `MessageTypeACLPolicy` checks each client's `allowed_types` whitelist during routing. See [Policy Admission Chain](policy.md).
- **Skill/intent blacklisting**: restrict which AI skills a specific satellite can trigger with `hivemind-core blacklist-skill` and `blacklist-intent` (`hivemind_core.scripts`).
- **Node-level isolation**: clients only receive messages meant for them, or broadcast to their permission level, as defined by `HiveMindNodeType` in `hivemind_core.protocol`.

---
[← Installation](installation.md) · [Home](index.md) · [Protocol →](protocol.md)
