# Policy Admission Chain

HiveMind's admission control is a chain of policy plugins. Every Mycroft
`Message` and every binary payload a client sends crosses the chain
before reaching the agent bus.

## Architecture

- `PolicyChain` (in `hivemind_core.policy`) holds an ordered list of
  `PolicyPlugin` instances and exposes three hooks: `review`,
  `review_binary`, and `observe`.
- For each `review`, the chain calls every policy in order. A policy
  returns a `Verdict` — either an allow (optionally carrying typed
  `Mutation` objects) or a deny (with a stable `code`, human-readable
  `reason`, and structured `data`).
- The first deny short-circuits the chain. Mutations from earlier allow
  verdicts are applied to the message before the next policy sees it.
- **Always fail-closed.** Any exception from a policy or from
  `Mutation.apply` is converted to `Verdict.deny("policy_error", ...)`
  with the offending policy/mutation name in `data`. There is no
  operator knob to flip this — the bus is unauthenticated and lenient-
  on-error would be a security footgun.
- `is_admin` on a client is **informational only**. The chain runner
  gives it no special treatment; policies that want admin-exemption
  branch on `client.is_admin` themselves.
- After a successful emit, the chain calls `observe()` on every policy
  for counters / audit logs. `observe` exceptions are swallowed.

## Authoring a Policy Plugin

Subclass `hivemind_plugin_manager.PolicyPlugin` and register under the
`hivemind.policy` entry-point group:

```toml
[project.entry-points."hivemind.policy"]
my-quota-policy = "my_pkg.policy:QuotaPolicy"
```

```python
from hivemind_plugin_manager import PolicyPlugin, Verdict, DenyCodes

class QuotaPolicy(PolicyPlugin):
    def review(self, message, client):
        if self._over_quota(client):
            return Verdict.deny(
                "quota_exceeded", "monthly cap reached",
                limit=self.config.get("limit", 100),
            )
        return Verdict.allow()
```

Use stable, machine-readable `code` strings. Common codes are exposed
as `DenyCodes` members; pick your own for plugin-specific reasons.

A policy can return one or more `Mutation` objects on an allow verdict
to change the message before downstream policies and the bus see it.
Mutation classes are agent-specific and live with the agent plugin
(e.g. `hivemind_ovos_agent_plugin` ships `AddBlacklistedSkill`,
`RewriteUtterance`, etc.).

## Built-in Policies

- **`MessageTypeACLPolicy`** — always present, non-removable, runs
  first. Enforces the per-client `allowed_types` whitelist; an empty
  whitelist denies everything (deny-by-default). Refreshes the
  whitelist from the database on every admission so
  `hivemind-core allow-msg` takes effect without a reconnect. Caches
  the resolved client row on the connection (`client.resolve_user`) so
  downstream policies skip a second DB hit.
- **`DenyAllPolicy`** — fail-closed fallback installed when
  `PolicyChain.from_config` raises. Denies every message and binary
  payload with `code="policy_chain_unavailable"`.
- **`OVOSAgentPolicy`** (in `hivemind-ovos-agent-plugin`) — optional,
  OVOS-specific. Enforces skill/intent blacklists, session-id rules,
  and ships agent-specific `Mutation` classes.

## Operator Configuration

```yaml
policy:
  chain:
    - module: my-quota-policy
      config:
        limit: 100
    - module: hivemind-ovos-agent-policy
    - module: my-experimental-policy
      optional: true
```

`MessageTypeACLPolicy` is implicit and always first — do not list it.

### `optional` flag

Per-chain-entry `optional: true` marks the policy as non-load-bearing:
if its `review` / `review_binary` raises, the chain logs a warning and
treats the verdict as allow (no mutations, chain continues). Default
is `false` — exceptions fail closed with `policy_error`. The implicit
`MessageTypeACLPolicy` is always mandatory and ignores this flag.

`allowed_types` is the canonical admission whitelist for a client.
Grant message types with `hivemind-core allow-msg <msg_type> <node_id>`;
revoke with `blacklist-msg`. Empty whitelist ⇒ deny everything.

There is no `policy.fail_open` knob. The chain is fail-closed by
design: a misbehaving policy denies rather than admits.

## Deny-Code Reference

Codes returned by built-in policies and the chain runner:

| Code | Source | Meaning |
| --- | --- | --- |
| `acl_disallowed_type` | `MessageTypeACLPolicy` | `msg_type` not in `allowed_types` |
| `policy_error` | `PolicyChain` | A policy or mutation raised; data carries `policy`, `error`, and optionally `mutation` |
| `policy_chain_unavailable` | `DenyAllPolicy` | Chain construction failed at startup |
| `session_id_default_forbidden` | `OVOSAgentPolicy` | Client tried to use the reserved `default` session id |

Plugin authors are free to mint their own `code` values; reuse a
built-in code only when the semantics match.

## CLI

- `hivemind-core policy list` — print the loaded chain (built-in first,
  then configured plugins).
- `hivemind-core policy test <api_key> <msg_type>` — dry-run a fake
  message through the chain and print the verdict as JSON.

## Wire Format: `hive.policy.denied`

When the chain returns a deny verdict, the client receives an
out-of-band notification routed via `HiveMessageType.THIRDPRTY`
(the signal channel, not the agent bus). The message payload:

```json
{
  "denied_type": "<original msg_type>",
  "code": "<DenyCode value>",
  "reason": "<human-readable>",
  "data": { "...": "policy-specific structured fields" }
}
```

- `denied_type` — the `msg_type` of the message that was rejected.
- `code` — stable machine-readable identifier; see the Deny-Code
  Reference above.
- `reason` — human-readable explanation for logs / UIs.
- `data` — free-form structured payload set by the policy
  (`msg_type`, `allowed`, `policy`, `error`, etc. depending on code).

Clients SHOULD branch on `code`; `reason` is informational only.
