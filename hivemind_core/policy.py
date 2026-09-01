# hivemind-core
# Copyright (C) 2026 Casimiro Ferreira
# SPDX-License-Identifier: Apache-2.0
"""Policy admission chain — consumer side of the primitives shipped in
hivemind-plugin-manager (PolicyPlugin / Verdict / Mutation).

Spec: https://github.com/JarbasHiveMind/HiveMind-core/issues/85
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from hivemind_plugin_manager import (DenyCodes, PolicyPlugin,
                                     PolicyPluginFactory, Verdict)
from ovos_bus_client.message import Message
from ovos_utils.log import LOG

if TYPE_CHECKING:
    from hivemind_core.protocol import HiveMindClientConnection

#: Reported to the client when a message passed admission but the agent bus
#: behind this node is unreachable, so nothing was forwarded. Not a policy
#: decision — the message is lost and the client should retry.
BACKEND_UNAVAILABLE = "backend_unavailable"

#: Reported to the client when the payload of a message can not be
#: reconstructed — a wrapper message (QUERY, BROADCAST, PROPAGATE, ESCALATE,
#: CASCADE) that does not carry a nested ``HiveMessage`` as HIVEMIND-MSG-1 §4
#: requires, a BUS or SHARED_BUS whose payload is not a bus ``Message``, or any
#: payload that is not a dict at all. Not a policy decision — the frame is
#: unusable and the sender must fix how it builds it.
MALFORMED_PAYLOAD = "malformed_payload"


@dataclass
class PolicyChain:
    """Ordered list of policy plugins evaluated for every admission decision.

    A verdict from one policy can either short-circuit the chain
    (``Verdict.deny``) or contribute mutations that are applied to the
    message before the next policy runs.

    **Always fail-closed.** Any exception raised by a policy (or by a
    mutation's ``apply``) is converted to ``Verdict.deny("policy_error",
    ...)``. There is no operator knob to disable this — the hivemind bus
    is unauthenticated and private; lenient-on-error behaviour would be
    a security footgun. A policy that wants to swallow its own errors
    can do so in its own ``try/except`` and return ``Verdict.allow()``.
    """

    policies: List[PolicyPlugin] = field(default_factory=list)
    on_verdict: Optional[Callable[[Optional[PolicyPlugin], Verdict], None]] = None
    # Parallel to ``policies``: True ⇒ exceptions from that policy are
    # logged and treated as Verdict.allow() (chain continues). False
    # (default) ⇒ exception fails the chain closed with POLICY_ERROR.
    # The force-prepended MessageTypeACLPolicy is always mandatory.
    _optional: List[bool] = field(default_factory=list)

    @classmethod
    def from_config(cls, config: Dict[str, Any],
                    hm_protocol: Optional[Any] = None) -> "PolicyChain":
        """Build a chain from server config.

        Config shape::

            {
              "policy": {
                "chain": [
                  {"module": "hivemind-intent-quota-policy",
                   "config": {"limit": 100}},
                  ...
                ]
              }
            }

        ``MessageTypeACLPolicy`` is **not** listed here — it is always
        prepended to the chain by ``HiveMindListenerProtocol`` and
        cannot be removed by configuration. The whitelist enforcement
        on ``allowed_types`` is the canonical admission gate.

        Raises if any configured plugin fails to instantiate — startup
        must crash rather than silently install a partial chain.
        """
        policy_cfg = config.get("policy") or {}
        chain_cfg = policy_cfg.get("chain") or []
        policies: List[PolicyPlugin] = []
        optional_flags: List[bool] = []
        for entry in chain_cfg:
            name = entry.get("module")
            if not name:
                continue
            try:
                plug = PolicyPluginFactory.create(
                    name, config=entry.get("config") or {},
                    hm_protocol=hm_protocol,
                )
                policies.append(plug)
                optional_flags.append(bool(entry.get("optional", False)))
                LOG.info(f"loaded policy plugin: {name}"
                         f"{' (optional)' if optional_flags[-1] else ''}")
            except Exception as e:
                LOG.error(f"failed to load policy plugin '{name}': {e}")
                raise
        return cls(policies=policies, _optional=optional_flags)

    def review(self, message: Message,
               client: "HiveMindClientConnection") -> Verdict:
        """Run every policy's ``review`` hook in order, applying mutations
        as we go. Returns the first deny verdict, or an allow verdict
        with the accumulated mutations already applied to ``message``.

        ``Client.is_admin`` is informational only — the runner does not
        skip any policy based on it. Policies that care about admin
        status branch on ``client.is_admin`` themselves.
        """
        accumulated: List = []
        for i, policy in enumerate(self.policies):
            is_optional = self._optional[i] if i < len(self._optional) else False
            try:
                verdict = policy.review(message, client)
            except Exception as e:
                if is_optional:
                    LOG.warning(
                        f"optional policy {type(policy).__name__} raised; "
                        f"continuing chain: {e}"
                    )
                    continue
                LOG.exception(f"policy {type(policy).__name__} raised")
                verdict = Verdict.deny(
                    DenyCodes.POLICY_ERROR, "policy raised",
                    policy=type(policy).__name__, error=str(e),
                )
                self._fire_on_verdict(policy, verdict)
                return verdict
            self._fire_on_verdict(policy, verdict)
            if verdict.denied:
                return verdict
            for mutation in verdict.mutations:
                try:
                    result = mutation.apply(message, client)
                    if result is not None:
                        message = result
                    accumulated.append(mutation)
                except Exception as e:
                    LOG.exception("mutation application failed")
                    return Verdict.deny(
                        DenyCodes.POLICY_ERROR, "mutation raised",
                        policy=type(policy).__name__,
                        mutation=type(mutation).__name__,
                        error=str(e),
                    )
        final = Verdict.allow(*accumulated)
        # Synthetic chain-complete trace: fire on_verdict with policy=None
        # so tracers can see the full accumulated mutation set.
        self._fire_on_verdict(None, final)
        return final

    def _fire_on_verdict(self, policy: Optional[PolicyPlugin], verdict: Verdict) -> None:
        """Invoke the optional ``on_verdict`` trace hook. Never raises —
        exceptions are logged and swallowed so a buggy tracer can't break
        the admission path."""
        if self.on_verdict is None:
            return
        try:
            self.on_verdict(policy, verdict)
        except Exception:
            LOG.exception("on_verdict tracer raised — ignored")

    def review_binary(self, payload: bytes,
                      client: "HiveMindClientConnection") -> Verdict:
        """Run every policy's ``review_binary`` hook. Mutations on a
        binary verdict are ignored (not supported); deny short-circuits.

        ``Client.is_admin`` is informational only here too — no
        runner-level bypass; policies branch on it themselves.
        """
        for i, policy in enumerate(self.policies):
            is_optional = self._optional[i] if i < len(self._optional) else False
            try:
                verdict = policy.review_binary(payload, client)
            except Exception as e:
                if is_optional:
                    LOG.warning(
                        f"optional policy {type(policy).__name__} "
                        f"review_binary raised; continuing chain: {e}"
                    )
                    continue
                LOG.exception(f"policy {type(policy).__name__} review_binary raised")
                return Verdict.deny(
                    DenyCodes.POLICY_ERROR, "policy raised",
                    policy=type(policy).__name__, error=str(e),
                )
            if verdict.denied:
                return verdict
            if verdict.mutations:
                LOG.warning(
                    f"policy {type(policy).__name__} returned mutations "
                    f"on a binary verdict — ignored (not supported)"
                )
        return Verdict.allow()

    def observe(self, message: Message,
                client: "HiveMindClientConnection") -> None:
        """Fire-and-forget post-admission hook. Exceptions are swallowed
        with a log; observers must never break the emit path.
        """
        for policy in self.policies:
            try:
                policy.observe(message, client)
            except Exception:
                LOG.exception(
                    f"policy {type(policy).__name__}.observe raised — ignored"
                )


class DenyAllPolicy(PolicyPlugin):
    """Fail-closed fallback policy installed when chain construction fails.

    Denies every inbound message + binary payload with
    ``code="policy_chain_unavailable"`` so operators see a loud signal
    in the client and in logs that the configured policy chain didn't
    build. Better than silently installing an empty (allow-all) chain.
    """

    REASON = (
        "policy chain failed to build; rejecting all admissions until "
        "configuration is fixed"
    )

    def review(self, message: Message,
               client: "HiveMindClientConnection") -> Verdict:
        return Verdict.deny(DenyCodes.POLICY_CHAIN_UNAVAILABLE, self.REASON)

    def review_binary(self, payload: bytes,
                       client: "HiveMindClientConnection") -> Verdict:
        return Verdict.deny(DenyCodes.POLICY_CHAIN_UNAVAILABLE, self.REASON)


class DefaultSessionPolicy(PolicyPlugin):
    """Built-in admission policy protecting the reserved ``"default"``
    session. Always present in the chain — non-removable.

    Every OVOS message that carries ``session_id == "default"`` updates the
    device-local default session of the host (OVOS-SESSION-2 §5), which the
    orchestrator owns. HIVEMIND-BRIDGE-1 §4.1 requires the bridge to deny an
    unauthorized peer the use of that id, so non-admin clients are denied
    here. Admins are exempt.

    ``OVOSAgentPolicy`` performs the same check, but operators remove it
    whenever they run a non-OVOS backend. The reserved id is a property of
    the bridge, not of one agent, so the gate belongs in core.

    Defense-in-depth note: in the live call graph,
    ``_install_client_session`` already NATs a non-admin's declared
    "default" to a per-connection Layer-1 id *before* the policy chain
    runs, so this policy currently never actually sees a literal
    "default" on a non-admin message — the check below is a backstop, not
    the primary gate. If a future refactor ever reorders the NAT after
    the policy chain, this policy becomes load-bearing; see
    ``tests/test_session_nat_ordering.py``.
    """

    def review(self, message: Message,
               client: "HiveMindClientConnection") -> Verdict:
        if client.is_admin:
            return Verdict.allow()
        session = (message.context or {}).get("session") or {}
        if isinstance(session, dict) and session.get("session_id") == "default":
            return Verdict.deny(
                DenyCodes.SESSION_ID_DEFAULT_FORBIDDEN,
                "non-admin clients may not inject 'default' session payloads",
                session_id="default",
            )
        return Verdict.allow()


class MessageTypeACLPolicy(PolicyPlugin):
    """Built-in admission policy enforcing the per-client ``allowed_types``
    whitelist. Always present in the chain — non-removable.

    Every client (admin or not) is denied when ``message.msg_type`` is
    not in ``client.allowed_types``. Empty ``allowed_types`` ⇒ deny
    everything (deny-by-default; the model is whitelist-only). Admins
    are not exempt — operators grant the message types they need via
    ``hivemind-core allow-msg`` like any other client.

    Binary payloads cross the same gate: a client with an empty
    whitelist is denied binary too (see ``review_binary``).

    Refreshes ``allowed_types`` from the DB on each admission so
    ``hivemind-core allow-msg`` / ``blacklist-msg`` take effect
    immediately without forcing a reconnect. A DB error is a deny, not
    a fallback to the connection snapshot — otherwise a revocation
    issued while the DB is down would never take effect.

    The resolved DB row is cached on the connection via
    ``client.resolve_user(db)`` so downstream policies in the same chain
    pass reuse it instead of issuing their own DB query.

    No mutations. Agent-specific concerns (skill/intent blacklists, etc.)
    live in agent policies like ``OVOSAgentPolicy``.
    """

    def _allowed_types(self, client: "HiveMindClientConnection") -> List[str]:
        """Resolve the whitelist for this admission.

        The DB row wins so a grant or a revocation takes effect without a
        reconnect; the snapshot taken at connection time is used only when
        there is no DB at all. DB errors propagate — both callers turn them
        into a POLICY_ERROR deny, never into a stale allow.
        """
        db = self.hm_protocol.db if self.hm_protocol is not None else None
        if db is None:
            return list(client.allowed_types or [])
        user = client.resolve_user(db)
        if user is None:
            return list(client.allowed_types or [])
        return list(user.allowed_types or [])

    def review(self, message: Message,
               client: "HiveMindClientConnection") -> Verdict:
        try:
            allowed = self._allowed_types(client)
        except Exception as e:
            LOG.exception("MessageTypeACLPolicy: failed to resolve allowed_types")
            return Verdict.deny(
                DenyCodes.POLICY_ERROR,
                f"MessageTypeACLPolicy: failed to resolve allowed_types: {e}",
            )

        msg_type = message.msg_type
        if msg_type not in allowed:
            return Verdict.deny(
                DenyCodes.ACL_DISALLOWED_TYPE,
                f"{msg_type} not in allowed_types",
                msg_type=msg_type,
                allowed=allowed,
            )
        return Verdict.allow()

    def review_binary(self, payload: bytes,
                      client: "HiveMindClientConnection") -> Verdict:
        """Binary payloads cross the same gate as bus messages.

        ``allowed_types`` lists message types, and the Client DB row has no
        per-``bin_type`` grant, so the only decision this policy can make on
        a binary payload is the deny-by-default one: a client with an empty
        whitelist is granted nothing and gets nothing. Without this a client
        that may not emit a single message type could still push RAW_AUDIO
        into the STT pipeline and FILE payloads to disk.
        """
        try:
            allowed = self._allowed_types(client)
        except Exception as e:
            LOG.exception("MessageTypeACLPolicy: failed to resolve allowed_types")
            return Verdict.deny(
                DenyCodes.POLICY_ERROR,
                f"MessageTypeACLPolicy: failed to resolve allowed_types: {e}",
            )

        if not allowed:
            return Verdict.deny(
                DenyCodes.ACL_DISALLOWED_TYPE,
                "binary payloads are denied for a client with an empty "
                "allowed_types whitelist",
                allowed=allowed,
            )
        return Verdict.allow()
