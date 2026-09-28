# Extending HiveMind Core

HiveMind Core is assembled from plugins. Every backend concern (database, transport,
agent, binary handling, and admission control) is a separate installable Python package
that registers itself under a setuptools entry-point group. It needs no changes to
hivemind-core itself.

The abstract base classes are defined in
[hivemind-plugin-manager](https://github.com/JarbasHiveMind/hivemind-plugin-manager).
This page summarizes how to wire a plugin to hivemind-core. For the full ABC contracts
and complete walkthroughs, see the
[plugin-manager docs](https://github.com/JarbasHiveMind/hivemind-plugin-manager/tree/dev/docs).

---

## Database Plugin

Store client credentials anywhere: SQLite, PostgreSQL, a REST API, an in-memory dict.

**Entry-point group:** `hivemind.database`

**Base class:** `hivemind_plugin_manager.database.AbstractDB` (local) or `AbstractRemoteDB` (network-backed)

**Minimal contract:**

```python
from dataclasses import dataclass
from typing import List, Iterable, Union
from hivemind_plugin_manager.database import AbstractDB, Client

@dataclass
class MyDB(AbstractDB):
    def add_item(self, client: Client) -> bool: ...
    def search_by_value(self, key, val) -> List[Client]: ...
    def __len__(self) -> int: ...
    def __iter__(self) -> Iterable[Client]: ...
```

**Schema migrations:** Override `migrate(from_version: int)` to handle data migrations
when `SCHEMA_VERSION` bumps. Implementations must be idempotent. The base class
`SCHEMA_VERSION = 2`; backends that skip `migrate` keep working via property shims on
`Client`.

**Registration:**

```toml
[project.entry-points."hivemind.database"]
my-db-plugin = "my_package.db:MyDB"
```

**Activation in server.json:**

```json
"database": {
  "module": "my-db-plugin",
  "my-db-plugin": {"host": "..."}
}
```

Full guide: [hivemind-plugin-manager/docs/plugins/database.md](https://github.com/JarbasHiveMind/hivemind-plugin-manager/blob/dev/docs/plugins/database.md)

---

## Network Protocol Plugin

Transport HiveMessages over any wire: MQTT, Unix sockets, raw TCP, Usenet.

**Entry-point group:** `hivemind.network.protocol`

**Base class:** `hivemind_plugin_manager.protocols.NetworkProtocol`

**Minimal contract:**

```python
from dataclasses import dataclass
from hivemind_plugin_manager.protocols import NetworkProtocol

@dataclass
class MyNetworkProtocol(NetworkProtocol):
    def run(self):
        # Block; accept connections, call self.hm_protocol.handle_message(...)
        # for each received HiveMessage.
        ...
```

**Registration:**

```toml
[project.entry-points."hivemind.network.protocol"]
my-transport-plugin = "my_package.transport:MyNetworkProtocol"
```

**Activation in server.json:**

```json
"network_protocol": {
  "my-transport-plugin": {"host": "0.0.0.0", "port": 9000}
}
```

Multiple network plugins run simultaneously. Full guide:
[hivemind-plugin-manager/docs/plugins/network-protocol.md](https://github.com/JarbasHiveMind/hivemind-plugin-manager/blob/dev/docs/plugins/network-protocol.md)

---

## Agent Protocol Plugin

Route HiveMessage payloads to any AI backend.

**Entry-point group:** `hivemind.agent.protocol`

**Base class:** `hivemind_plugin_manager.protocols.AgentProtocol`

**Mandatory method:**

```python
def natural_language_query(self, utterance: str,
                           lang: str) -> Iterator[Optional[str]]:
    # Yield answer chunks; yield None as end-of-query sentinel.
    ...
```

Yield `None` immediately if the agent has no answer (triggers upstream escalation).

**Entry point hivemind-core calls:**

```python
def answer_query(self, utterance: str, lang: str,
                 client: Optional[HiveMindClientConnection] = None
                 ) -> Iterator[Optional[str]]:
    ...
```

The QUERY and CASCADE handlers call `answer_query`, not `natural_language_query`. The
base implementation ignores `client` and delegates to `natural_language_query`, so a
plugin only implements the primitive. Override `answer_query` when the agent needs the
caller's identity, for example to dispatch to one sub-agent per access key.

**Registration:**

```toml
[project.entry-points."hivemind.agent.protocol"]
my-agent-plugin = "my_package.agent:MyAgentProtocol"
```

**Activation in server.json:**

```json
"agent_protocol": {
  "module": "my-agent-plugin",
  "my-agent-plugin": {"endpoint": "http://localhost:8080"}
}
```

Full guide:
[hivemind-plugin-manager/docs/plugins/agent-protocol.md](https://github.com/JarbasHiveMind/hivemind-plugin-manager/blob/dev/docs/plugins/agent-protocol.md)

---

## Binary Data Handler Plugin

Process server-side audio, images, or arbitrary binary payloads.

**Entry-point group:** `hivemind.binary.protocol`

**Base class:** `hivemind_plugin_manager.protocols.BinaryDataHandlerProtocol`

Override one or more handler methods:

```python
def handle_microphone_input(self, bin_data, sample_rate, sample_width, client): ...
def handle_stt_transcribe_request(self, bin_data, sample_rate, sample_width, lang, client): ...
def handle_stt_handle_request(self, bin_data, sample_rate, sample_width, lang, client): ...
def handle_numpy_image(self, bin_data, camera_id, client): ...
def handle_receive_tts(self, bin_data, utterance, lang, file_name, client): ...
def handle_receive_file(self, bin_data, file_name, client): ...
```

The default for each is a logged no-op (warn + ignore).

**Registration:**

```toml
[project.entry-points."hivemind.binary.protocol"]
my-audio-plugin = "my_package.audio:MyAudioProtocol"
```

**Activation in server.json:**

```json
"binary_protocol": {"module": "my-audio-plugin"}
```

Full guide:
[hivemind-plugin-manager/docs/plugins/binary-protocol.md](https://github.com/JarbasHiveMind/hivemind-plugin-manager/blob/dev/docs/plugins/binary-protocol.md)

---

## Policy Plugin

Implement admission-control, rate limiting, metadata injection, or audit logging.

**Entry-point group:** `hivemind.policy`

**Base class:** `hivemind_plugin_manager.policy.PolicyPlugin`

```python
from dataclasses import dataclass
from hivemind_plugin_manager.policy import PolicyPlugin, Verdict

@dataclass
class MyPolicy(PolicyPlugin):
    def review(self, message, client) -> Verdict:
        if self._should_deny(message, client):
            return Verdict.deny("my_reason", "human-readable explanation")
        return Verdict.allow()

    def observe(self, message, client) -> None:
        # Called after a message is emitted. For counters/audit. Must not raise.
        pass
```

**Registration:**

```toml
[project.entry-points."hivemind.policy"]
my-policy = "my_package.policy:MyPolicy"
```

**Activation in server.json:**

```json
"policy": {
  "chain": [
    {"module": "hivemind-ovos-agent-policy"},
    {"module": "my-policy", "config": {"limit": 500}}
  ]
}
```

`MessageTypeACLPolicy` and `DefaultSessionPolicy` are implicit and
always first. Do not list them.
Full guide: [docs/policy.md](policy.md) and
[hivemind-plugin-manager/docs/plugins/policy.md](https://github.com/JarbasHiveMind/hivemind-plugin-manager/blob/dev/docs/plugins/policy.md)

---
[← Plugins](plugins.md) · [Home](README.md)
