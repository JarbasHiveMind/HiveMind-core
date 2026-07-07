# hivemind-core
# Copyright (C) 2026 Casimiro Ferreira
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
"""Policy admission chain — consumer side of the primitives shipped in
hivemind-plugin-manager (PolicyPlugin / Verdict / Mutation).

Spec: https://github.com/JarbasHiveMind/HiveMind-core/issues/85
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from hivemind_plugin_manager import (DenyCodes, PolicyPlugin,
                                     PolicyPluginFactory, Verdict)
from ovos_bus_client.message import Message
from ovos_utils.log import LOG

if TYPE_CHECKING:
    from hivemind_core.protocol import HiveMindClientConnection


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def _optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    return int(value)


def _busy_verdict(reason: str, **data: Any) -> Verdict:
    """Return a retryable admission-busy verdict.

    Newer hivemind-plugin-manager releases provide ``Verdict.busy`` and
    ``DenyCodes.POLICY_BUSY``. Keep a small fallback here so core can be
    reviewed and tested before that dependency is released.
    """
    busy = getattr(Verdict, "busy", None)
    if callable(busy):
        return busy(reason, **data)
    code = getattr(DenyCodes, "POLICY_BUSY", "policy_busy")
    return Verdict.deny(code, reason, **data)


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
    # Admission timing guardrails. Warns are observability only; max_review_ms
    # turns an over-budget allow into a retryable "policy_busy" denial.
    warn_review_ms: Optional[float] = None
    max_review_ms: Optional[float] = None
    busy_retry_after_ms: Optional[int] = None

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
        return cls(
            policies=policies,
            _optional=optional_flags,
            warn_review_ms=_optional_float(policy_cfg.get("warn_review_ms")),
            max_review_ms=_optional_float(policy_cfg.get("max_review_ms")),
            busy_retry_after_ms=_optional_int(policy_cfg.get("busy_retry_after_ms")),
        )

    def _budget_verdict(self, started_at: float, policy_started_at: float,
                        policy: PolicyPlugin, path: str) -> Optional[Verdict]:
        now = time.monotonic()
        elapsed_ms = (now - started_at) * 1000.0
        policy_ms = (now - policy_started_at) * 1000.0
        policy_name = type(policy).__name__

        if self.warn_review_ms is not None and elapsed_ms > self.warn_review_ms:
            LOG.warning(
                "policy admission slow: path=%s policy=%s policy_ms=%.2f "
                "elapsed_ms=%.2f warn_ms=%.2f",
                path, policy_name, policy_ms, elapsed_ms, self.warn_review_ms,
            )

        if self.max_review_ms is None or elapsed_ms <= self.max_review_ms:
            return None

        data: Dict[str, Any] = {
            "path": path,
            "policy": policy_name,
            "policy_ms": round(policy_ms, 2),
            "elapsed_ms": round(elapsed_ms, 2),
            "budget_ms": round(self.max_review_ms, 2),
        }
        if self.busy_retry_after_ms is not None:
            data["retry_after_ms"] = self.busy_retry_after_ms
        return _busy_verdict("policy admission exceeded time budget", **data)

    def review(self, message: Message,
               client: "HiveMindClientConnection") -> Verdict:
        """Run every policy's ``review`` hook in order, applying mutations
        as we go. Returns the first deny verdict, or an allow verdict
        with the accumulated mutations already applied to ``message``.

        ``Client.is_admin`` is informational only — the runner does not
        skip any policy based on it. Policies that care about admin
        status branch on ``client.is_admin`` themselves.
        """
        budget_enabled = bool(self.policies) and (
            self.warn_review_ms is not None or self.max_review_ms is not None
        )
        started_at = time.monotonic() if budget_enabled else 0.0
        accumulated: List = []
        for i, policy in enumerate(self.policies):
            is_optional = self._optional[i] if i < len(self._optional) else False
            policy_started_at = time.monotonic() if budget_enabled else 0.0
            try:
                verdict = policy.review(message, client)
            except Exception as e:
                if is_optional:
                    LOG.warning(
                        f"optional policy {type(policy).__name__} raised; "
                        f"continuing chain: {e}"
                    )
                    if budget_enabled:
                        budget_verdict = self._budget_verdict(
                            started_at, policy_started_at, policy, "message",
                        )
                        if budget_verdict is not None:
                            self._fire_on_verdict(policy, budget_verdict)
                            return budget_verdict
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
            if budget_enabled:
                budget_verdict = self._budget_verdict(
                    started_at, policy_started_at, policy, "message",
                )
                if budget_verdict is not None:
                    self._fire_on_verdict(policy, budget_verdict)
                    return budget_verdict
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
        budget_enabled = bool(self.policies) and (
            self.warn_review_ms is not None or self.max_review_ms is not None
        )
        started_at = time.monotonic() if budget_enabled else 0.0
        for i, policy in enumerate(self.policies):
            is_optional = self._optional[i] if i < len(self._optional) else False
            policy_started_at = time.monotonic() if budget_enabled else 0.0
            try:
                verdict = policy.review_binary(payload, client)
            except Exception as e:
                if is_optional:
                    LOG.warning(
                        f"optional policy {type(policy).__name__} "
                        f"review_binary raised; continuing chain: {e}"
                    )
                    if budget_enabled:
                        budget_verdict = self._budget_verdict(
                            started_at, policy_started_at, policy, "binary",
                        )
                        if budget_verdict is not None:
                            return budget_verdict
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
            if budget_enabled:
                budget_verdict = self._budget_verdict(
                    started_at, policy_started_at, policy, "binary",
                )
                if budget_verdict is not None:
                    return budget_verdict
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


class MessageTypeACLPolicy(PolicyPlugin):
    """Built-in admission policy enforcing the per-client ``allowed_types``
    whitelist. Always present in the chain — non-removable.

    Every client (admin or not) is denied when ``message.msg_type`` is
    not in ``client.allowed_types``. Empty ``allowed_types`` ⇒ deny
    everything (deny-by-default; the model is whitelist-only). Admins
    are not exempt — operators grant the message types they need via
    ``hivemind-core allow-msg`` like any other client.

    Refreshes ``allowed_types`` from the DB on each admission so
    ``hivemind-core allow-msg`` / ``blacklist-msg`` take effect
    immediately without forcing a reconnect.

    The resolved DB row is cached on the connection via
    ``client.resolve_user(db)`` so downstream policies in the same chain
    pass reuse it instead of issuing their own DB query.

    No mutations. Agent-specific concerns (skill/intent blacklists, etc.)
    live in agent policies like ``OVOSAgentPolicy``.
    """

    def review(self, message: Message,
               client: "HiveMindClientConnection") -> Verdict:
        allowed = list(getattr(client, "allowed_types", []) or [])
        db = getattr(self.hm_protocol, "db", None)
        if db is not None:
            try:
                user = client.resolve_user(db)
                if user is not None:
                    allowed = list(getattr(user, "allowed_types", allowed) or [])
            except Exception:
                LOG.warning("MessageTypeACLPolicy: DB refresh failed; using cached value",
                            exc_info=True)

        msg_type = getattr(message, "msg_type", None)
        if msg_type not in allowed:
            return Verdict.deny(
                DenyCodes.ACL_DISALLOWED_TYPE,
                f"{msg_type} not in allowed_types",
                msg_type=msg_type,
                allowed=allowed,
            )
        return Verdict.allow()
