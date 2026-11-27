# AGENTS.md — HiveMind-core

HiveMind-core is the hub of a HiveMind network. It listens for satellite connections, runs the Noise handshake and the admission chain that decides what each client may send, routes messages between satellites and the agent backend (OpenVoiceOS or another plugin), and owns the client database. The wire protocol lives in `hivemind_bus_client`. Plugin contracts live in `hivemind-plugin-manager`. User docs are in `docs/` (start at `docs/index.md`).

## Repository map

| Path | Contents |
| :--- | :--- |
| `hivemind_core/protocol.py` | listener protocol, Noise handshake, rate limit, pins, inbound gates, routing |
| `hivemind_core/policy.py` | `PolicyChain`, built-in policies, deny codes |
| `hivemind_core/service.py` | process start-up, plugin loading, upstream connection, node identity |
| `hivemind_core/config.py` | `server.json` defaults (`_DEFAULT`) and loading |
| `hivemind_core/database.py` | `ClientDatabase`, a wrapper over a database plugin |
| `hivemind_core/scripts.py` | the `hivemind-core` CLI |
| `tests/` | unit tests |
| `tests/e2e/` | tests that start a real hub through `hivescope`; do not add a second test directory |
| `docs/` | user documentation |

## Setup and tests

```bash
uv venv
uv pip install --python .venv/bin/python --prerelease=allow -e ".[test,integration]"
.venv/bin/python -m pytest tests -q
```

- `conftest.py` loads the `hivescope` pytest plugin only when `hivescope` is installed. A unit run without the extras passes without the e2e fixtures.
- When a change touches `protocol.py`, `policy.py` or `database.py`, run `tests/e2e/` too. The e2e tests are the ground truth for protocol behaviour.
- A regression test fails before the fix and passes after it. Prove it with `git apply -R` on the source only.
- A test asserts real behaviour, not only that a mock was called. Never skip a test because an optional dependency is missing.

## Dependencies

- Floor pins only (`>=X.Y.Za1`), each bump with a one-line comment that says why. No upper cap unless a named release is broken. No lockfiles. Never install from git.
- All metadata is in `pyproject.toml`.
- The licence is Apache-2.0. Do not add GPL or AGPL dependencies.

## Git and pull requests

- Work on a feature branch and open a draft PR against `dev`. Never push to `dev` or `master`. Never touch `Release X → master` PRs.
- Conventional commits: `feat:` only for a user-visible capability; otherwise `fix:`, `docs:`, `chore:`, `ci:`. PRs are squash-merged.
- An agent PR, issue or comment opens with an AI disclosure that names the model and says that no human reviewed it.
- No scratch files, virtualenvs, `__pycache__`, `.pyc`, `.egg-info` or build artefacts in a PR.

## Rules that the code enforces

- Wire back-compat is load-bearing. The hub talks to clients of older and newer library versions at the same time. Never change the wire shape of an existing `HiveMessageType`, and never add a bus message type. Decoding stays tolerant of fields that a legacy client omits.
- Admission fails closed. `PolicyChain` turns a policy exception into a `policy_error` deny. A chain that does not build becomes `DenyAllPolicy`. When a decision is missing, deny with an existing code (`BACKEND_UNAVAILABLE`, `MALFORMED_PAYLOAD` in `policy.py`). Never add a path that forwards a message without a policy decision.
- `MessageTypeACLPolicy` and `DefaultSessionPolicy` always run first. Configuration cannot remove them.
- The Noise handshake is the only key exchange. TLS on a transport is optional and is not the security layer.
- `ClientDatabase` goes through the plugin interface. Do not assume a storage backend.
- `server.json` keys come from `config.py:_DEFAULT`. A key added there gets a row in `docs/configuration.md`; the page `verify` command compares the two.
