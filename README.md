# HiveMind-core
<!-- agent-hint
covers: what hivemind-core does, how to install it, one quickstart, links into docs/
source: pyproject.toml, hivemind_core/scripts.py
generated: no
verify: hivemind-core add-client --help >/dev/null 2>&1 && hivemind-core listen --help >/dev/null 2>&1 && for f in $(grep -o '(docs/[a-z0-9-]*\.md)' README.md | tr -d '()'); do test -f "$f" || exit 1; done
see: docs/index.md
-->

HiveMind-core is the hub of a [HiveMind](https://github.com/JarbasHiveMind) network. Satellites, bridges and other hubs connect to it. The hub authenticates each connection with a Noise handshake, checks each message against a per-client whitelist and a policy chain, and passes the message to an agent such as [OpenVoiceOS](https://github.com/OpenVoiceOS). Plugins supply the transport, the agent, the binary handler and the client database.

## Install

```bash
uv pip install --prerelease=allow hivemind-core
```

## Quickstart

Add a client and grant it the message types that it sends:

```text
$ hivemind-core add-client --name kitchen --allow ovos.utterance.handle --allow recognizer_loop:utterance
Database backend: SQLiteDB
Credentials added to database!

Node ID: 1
Admin Privileges: False
Friendly Name: kitchen
Access Key: 0123456789abcdef0123456789abcdef
Password: correct-horse-battery-staple-91
Allowed Message Types: ovos.utterance.handle, recognizer_loop:utterance
```

This output comes from a run with `--access-key` and `--password` set. Without them, the hub makes random values. Give the access key and the password to the satellite, then start the hub:

```bash
hivemind-core listen
```

The hub listens for WebSocket connections on port 5678 and connects to the OpenVoiceOS message bus on `127.0.0.1:8181`.

## Documentation

| Page | Contents |
| :--- | :--- |
| [Install and run a hub](docs/install-and-run.md) | install, first client, start, files |
| [Add and manage clients](docs/clients.md) | the `hivemind-core` CLI |
| [Configuration reference](docs/configuration.md) | each key of `server.json` |
| [Security model](docs/security.md) | Noise handshake, key pin, rate limit, inbound gates |
| [Policies and ACLs](docs/policies.md) | whitelist and policy chain |
| [Plugins](docs/plugins.md) | network, agent, binary and database plugins |
| [Troubleshooting](docs/troubleshooting.md) | log messages and their fixes |
| [Contributing and tests](docs/contributing.md) | development setup and tests |

The [HiveMind community docs](https://jarbashivemind.github.io/HiveMind-community-docs/) describe the protocol, the satellites and the bridges. For support, join the [HiveMind Matrix chat](https://matrix.to/#/#jarbashivemind:matrix.org).

## Licence

HiveMind-core is under the [Apache License 2.0](LICENSE). Releases 3.4.1a4 to 4.2.0a1, the stable 4.0.0 included, were under AGPL-3.0. Each published release keeps the licence that it was published with. The HiveMind names and logos are trademarks and are not part of the licence: see [TRADEMARK-USAGE.md](TRADEMARK-USAGE.md). For sponsorship or paid support, write to [jarbasai@mailfence.com](mailto:jarbasai@mailfence.com).
