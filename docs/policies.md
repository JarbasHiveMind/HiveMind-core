# Policies and ACLs
<!-- agent-hint
covers: the message type whitelist, the policy chain, its configuration and the hive.policy.denied reply
source: hivemind_core/policy.py, hivemind_core/protocol.py:_with_builtin_policies, hivemind_core/protocol.py:_send_denied, hivemind_core/scripts.py:policy_list
generated: no
verify: grep -q 'builtins = (MessageTypeACLPolicy, DefaultSessionPolicy)' hivemind_core/protocol.py && grep -q '0 │ MessageTypeACLPolicy' docs/policies.md && grep -q '1 │ DefaultSessionPolicy' docs/policies.md && python3 -c "import sys; from hivemind_plugin_manager import DenyCodes; doc=open('docs/policies.md').read(); sys.exit(0 if all(c.value in doc for c in DenyCodes) else 1)"
see: plugins.md
-->

The policy chain decides, for each message from a client, if the hub sends it to the agent. This page shows how to read the chain, test a client against it and add a policy.

## Example

```text
$ hivemind-core policy list
                Policy Chain
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ Position ┃ Plugin               ┃ Source  ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│        0 │ MessageTypeACLPolicy │ builtin │
│        1 │ DefaultSessionPolicy │ builtin │
│        2 │ OVOSAgentPolicy      │ config  │
└──────────┴──────────────────────┴─────────┘
```

Test one message type for one client. The client `kitchen` has the types `ovos.utterance.handle`, `recognizer_loop:utterance` and `speak`:

```text
$ hivemind-core policy test 0123456789abcdef0123456789abcdef speak
{
  "denied": false,
  "code": "",
  "reason": "",
  "data": {},
  "mutations": []
}
$ hivemind-core policy test 0123456789abcdef0123456789abcdef bus
{
  "denied": true,
  "code": "acl_disallowed_type",
  "reason": "bus not in allowed_types",
  "data": {
    "msg_type": "bus",
    "allowed": [
      "ovos.utterance.handle",
      "recognizer_loop:utterance",
      "speak"
    ]
  },
  "mutations": []
}
```

## Steps

### Grant message types

The message type ACL is a whitelist. A client can send only the types in its `allowed_types` list. A client with an empty list can send nothing, and no binary payload. Admin clients follow the same rule.

1. Grant each type that the client sends: `hivemind-core allow-msg ovos.utterance.handle recognizer_loop:utterance 1`.
2. Remove a type: `hivemind-core blacklist-msg speak 1`.
3. Test the result: `hivemind-core policy test <access key> <type>`.

The hub compares the exact type name. OpenVoiceOS sends `ovos.utterance.handle`, and older clients send `recognizer_loop:utterance`. Grant both when you do not know the client version.

### Add a policy

1. Install the policy plugin. It registers under the `hivemind.policy` entry point.
2. Add it to `policy.chain` in `server.json`:

   ```json
   "policy": {
     "chain": [
       {"module": "hivemind-ovos-agent-policy"},
       {"module": "my-quota-policy", "config": {"limit": 100}, "optional": true}
     ]
   }
   ```

3. Run `hivemind-core policy list` and look for the plugin.

### Block a skill or an intent

`OVOSAgentPolicy` comes with `hivemind-ovos-agent-plugin`. It reads `skill_blacklist` and `intent_blacklist` from the client metadata. Edit the lists with `blacklist-skill`, `allow-skill`, `blacklist-intent` and `allow-intent`. These commands have an effect only when `hivemind-ovos-agent-policy` is in the chain.

## Reference

### The chain

| Position | Policy | Removable | Effect |
| :--- | :--- | :--- | :--- |
| 0 | `MessageTypeACLPolicy` | no | denies a type that is not in `allowed_types` |
| 1 | `DefaultSessionPolicy` | no | denies a non-admin message that uses the session id `default` |
| 2 and on | the entries of `policy.chain` | yes | the plugin decides |

The policies run in order. The first deny stops the chain. A policy can also return mutations, which change the message before the next policy runs. Binary payloads pass the chain too, without mutations.

The chain fails closed. When a policy raises an exception, the result is a deny with code `policy_error`. An entry with `"optional": true` is the exception: its error goes to the log, and the chain continues. When the chain cannot be built from the configuration, the hub installs `DenyAllPolicy`, which denies each message with code `policy_chain_unavailable`. The log says `failed to build policy chain; installing DenyAllPolicy fallback`.

### Entry keys

| Key | Effect |
| :--- | :--- |
| `module` | the entry point name of the plugin |
| `config` | a JSON object that the plugin receives |
| `optional` | `true` lets the chain continue when this plugin raises an exception |

### The deny reply

A client that sends a denied message gets a `hive.policy.denied` bus message:

```json
{
  "denied_type": "<message type, or binary>",
  "code": "<deny code>",
  "reason": "<text>",
  "data": {}
}
```

| Code | Cause |
| :--- | :--- |
| `acl_disallowed_type` | the type is not in `allowed_types` |
| `session_id_default_forbidden` | a non-admin client used the `default` session |
| `policy_error` | a policy or a mutation raised an exception |
| `policy_chain_unavailable` | the chain did not build; `DenyAllPolicy` is installed |
| `malformed_payload` | the payload cannot be rebuilt as a message |
| `backend_unavailable` | the message passed the chain, but the agent bus is not available |

A plugin can return other codes.

---
[← Security model](security.md) · [Home](index.md) · [Plugins →](plugins.md)
