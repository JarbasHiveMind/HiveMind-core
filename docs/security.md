# Security and Encryption

HiveMind Core secures communication between the server and its satellites with the `poorman_handshake` library as its cryptographic foundation.

## Handshake and Key Exchange

HiveMind Core uses the `poorman_handshake` Noise handshake for authentication and transport key setup, managed by `HiveMindClientConnection` in `hivemind_core.protocol`.

1. **Identity**: every client has an `Access Key` and a `Password` stored through `hivemind_core.database.ClientDatabase`. The access key admits the client; the password derives the Noise pre-shared key.
2. **Noise handshake**: the v3 Noise handshake (XXpsk2/KKpsk0) is the sole key exchange. It authenticates both ends against the shared password and establishes a forward-secret, always-encrypted transport (HIVEMIND-CRYPTO-1 §3.4). A connection that cannot complete it is rejected with a `1008` close — there is no legacy fallback.
3. **PSK**: the pre-shared key is `argon2id(password, SHA-256(node_id))`. A constrained device that cannot run argon2id on-device flashes the value that `hivemind-core derive-psk` prints.
4. **Static-key pinning**: the server pins the client's Noise static key on first use (TOFU) and rejects a later contradicting key, so a reinstalled client must clear the pin with `hivemind-core reset-noise-pin`.
5. **Cipher/encoding**: the Noise suite fixes the AEAD cipher; `encodings` negotiate framing only. A v3 session is encrypted regardless of the chosen encoding.

## Encryption Standards

- **ChaCha20-Poly1305** and **AES-256-GCM**: the AEAD ciphers the Noise transport uses, giving both confidentiality and data integrity.
- **argon2id**: derives the Noise pre-shared key from the password, resisting brute-force attacks.
- **RSA**: used for `INTERCOM` messages, so nodes can exchange end-to-end encrypted messages that a relay node cannot read. The server verifies the origin signature and pins the sender's public key on first sighting. An `INTERCOM` frame with no signed envelope proves nothing about its origin, so the server drops it instead of relaying it.

## Permissions and Access Control

The server enforces access control through `ClientDatabase` and `HiveMindClientConnection`:

- **Message whitelist**: `MessageTypeACLPolicy` checks each client's `allowed_types` whitelist during routing. See [Policy Admission Chain](policy.md).
- **Skill/intent blacklisting**: restrict which AI skills a specific satellite can trigger with `hivemind-core blacklist-skill` and `blacklist-intent` (`hivemind_core.scripts`).
- **Node-level isolation**: clients only receive messages meant for them, or broadcast to their permission level, as defined by `HiveMindNodeType` in `hivemind_core.protocol`.
- **QUERY/CASCADE response routing**: `is_response` metadata on a QUERY or CASCADE message is checked against the same `can_escalate`/`can_propagate` permission as an original request, and checked before the response is routed. `_route_query_response` trusts `metadata.originator_peer` as a bare delivery address, with no proof the sender ever took part in that `query_id`; without the permission gate, a client with no escalate/propagate rights could forge `{"is_response": true, "originator_peer": <victim>}` around an arbitrary payload and have it delivered to the victim's connection.

  This closes the unprivileged forgery path, not every forgery path: a client that does hold escalate/propagate permission can still address a response at a peer for a query it never participated in, because the server keeps no per-query record of who actually asked, and routing trusts the sender's own claimed `originator_peer`. A privileged sender is still bounded by whatever the message-type ACL and its own permission scope allow, but response addressing itself is not verified against the query.

---
[← Installation](installation.md) · [Home](index.md) · [Protocol →](protocol.md)
