# Troubleshooting
<!-- agent-hint
covers: the hub log messages and client replies that operators meet, with the cause and the fix of each
source: hivemind_core/protocol.py, hivemind_core/service.py, hivemind_core/config.py:ServerConfigError, hivemind_core/policy.py
generated: no
verify: for s in 'contradicts the pinned key' 'too many failed handshakes' 'requires protocol v3' 'No network protocols were loaded' 'is not valid JSON' 'installing DenyAllPolicy' 'could not generate a node public key'; do grep -rqF "$s" hivemind_core || exit 1; grep -qF "$s" docs/troubleshooting.md || exit 1; done
see: contributing.md
-->

This page lists the problems that operators meet most, with the log text or the reply that shows each one. The hub log is `~/.local/state/mycroft/hivemind.log`.

## Example

A satellite connects, but nothing happens when it speaks. Test its access key against the policy chain:

```text
$ hivemind-core policy test 8af90631d5f749b60adaf00370585d6f ovos.utterance.handle
{
  "denied": true,
  "code": "acl_disallowed_type",
  "reason": "ovos.utterance.handle not in allowed_types",
  "data": {
    "msg_type": "ovos.utterance.handle",
    "allowed": []
  },
  "mutations": []
}
```

The client has no message types. Grant them with `hivemind-core allow-msg ovos.utterance.handle recognizer_loop:utterance 2`.

## Steps

1. Find the symptom in the table below.
2. Do the fix.
3. Test again with `hivemind-core policy test <access key> <type>`, or connect the client again.

## Reference

### Connection and handshake

| Log text or close reason | Cause | Fix |
| :--- | :--- | :--- |
| `client Noise static key contradicts the pinned key` | the client presents a Noise static key that is different from the pin | when the client was reinstalled or moved, run `hivemind-core reset-noise-pin <id>`; otherwise find the device that uses the credentials |
| `too many failed handshakes` | the access key or the IP reached the handshake rate limit | make sure that the client has the correct password, then wait for `handshake_failure_window` seconds |
| `this node requires protocol v3 (the Noise handshake)` | the client cannot do the Noise handshake, or it gave no password | upgrade the client library (`hivemind-bus-client`) |
| `pattern/suite not offered` | the client picked a Noise pattern or suite that the hub did not offer | upgrade the client library |

A wrong password fails on the client side. The hub sees a client that closes the connection during the handshake, and counts a failed handshake. Compare the password on the client with the output of `hivemind-core export-clients`.

### Messages

| Reply or log text | Cause | Fix |
| :--- | :--- | :--- |
| `hive.policy.denied`, code `acl_disallowed_type` | the type is not in `allowed_types` | `hivemind-core allow-msg <type> <id>` |
| `hive.policy.denied`, code `session_id_default_forbidden` | a non-admin client used the `default` session | send another session id, or make the client an admin |
| `hive.policy.denied`, code `backend_unavailable` | the agent bus is not available | start the agent; for OpenVoiceOS, the message bus on `127.0.0.1:8181` |
| `hive.policy.denied`, code `policy_chain_unavailable` | the policy chain did not build | read the log line `failed to build policy chain; installing DenyAllPolicy fallback`, then fix `policy.chain` |
| close code 4003 | the client sent BROADCAST, PROPAGATE, ESCALATE, QUERY or CASCADE without the permission | grant it with `allow-broadcast`, `allow-propagate` or `allow-escalate`; BROADCAST also needs `make-admin` |

### Start-up

| Log text or error | Cause | Fix |
| :--- | :--- | :--- |
| `... is not valid JSON ...` | `server.json` does not parse | fix the file, or remove it to start from the defaults; the hub does not change it |
| `network transport '<name>' is enabled in server.json (network_protocol) but is not installed` | a transport in `network_protocol` is not installed | install the package that the message names, or remove the key |
| `No network protocols were loaded. Exiting service.` | no transport started | install `hivemind-websocket-protocol`, or fix `network_protocol` |
| `could not generate a node public key, continuing without one` | the hub has no node identity and cannot write one | the hub serves clients, but other nodes cannot map it or address it by INTERCOM; the traceback under the line names the identity file and the `hivemind-client set-identity` command that sets it |
| `policy.fail_open is no longer honoured` | `server.json` holds the key `policy.fail_open` | remove the key |

### Bus events

The hub sends these messages on the agent bus. Use them to watch connections from an agent or a skill.

| Message | Data |
| :--- | :--- |
| `hive.client.connect` | `key`, `peer`, `session_id` |
| `hive.client.disconnect` | `key`, `peer` |
| `hive.client.connection.error` | `error`, `peer` |

`key` is the access key, and two connections can share it. `peer` is different for each connection.

---
[← Plugins](plugins.md) · [Home](index.md) · [Contributing and tests →](contributing.md)
