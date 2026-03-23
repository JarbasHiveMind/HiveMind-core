# Audit — hivemind-core

## Critical

| ID | Description | Location |
|----|-------------|----------|
| HC-001 | INTERCOM RSA signatures never verified — any peer can forge INTERCOM messages | `protocol.py:830-835` |
| HC-002 | `HiveMindClientConnection.__post_init__` accesses `self.hm_protocol.identity.private_key` without null check — crashes if identity unset | `protocol.py:112` |

## Medium

| ID | Description | Location |
|----|-------------|----------|
| HC-003 | Bare `except:` in callback handlers catches `SystemExit`/`KeyboardInterrupt` — should be `except Exception:` | `protocol.py:266,271,276,349,354,359` |
| HC-004 | `assert` in production code disabled with `-O` flag — replace with explicit check | `protocol.py:475` |
| HC-005 | `_unpack_message` no type validation on payload — accepts arbitrary data | `protocol.py:659-666` |
| HC-006 | `HiveMapper._seen_pings` dict grows unbounded — memory leak under sustained use | `hive_map.py:49` |
| HC-007 | Inconsistent naming: `_seen_pings` vs `_seen_flood_ids` — confusing for contributors | `hive_map.py:49` |

## Low

| ID | Description | Location |
|----|-------------|----------|
| HC-008 | `pub_key` database field not implemented (TODO) | `protocol.py:85` |
| HC-009 | Plaintext message rejection incomplete (TODO) | `protocol.py:196` |
| HC-010 | Intent/skill authorization check incomplete (TODO) | `protocol.py:214` |
| HC-011 | Numpy array conversion not implemented (TODO) | `protocol.py:500` |
| HC-012 | Invalid handshake handler not implemented (TODO) | `protocol.py:539,566` |
