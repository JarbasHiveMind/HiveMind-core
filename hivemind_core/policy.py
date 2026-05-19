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

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from hivemind_plugin_manager import PolicyPlugin, PolicyPluginFactory, Verdict
from ovos_bus_client.message import Message
from ovos_utils.log import LOG

if TYPE_CHECKING:
    from hivemind_core.protocol import HiveMindClientConnection


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

        ``ClientACLPolicy`` is **not** listed here — it is always
        prepended to the chain by ``HiveMindListenerProtocol`` and
        cannot be removed by configuration. The whitelist enforcement
        on ``allowed_types`` is the canonical admission gate.

        Raises if any configured plugin fails to instantiate — startup
        must crash rather than silently install a partial chain.
        """
        policy_cfg = config.get("policy") or {}
        chain_cfg = policy_cfg.get("chain") or []
        policies: List[PolicyPlugin] = []
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
                LOG.info(f"loaded policy plugin: {name}")
            except Exception as e:
                LOG.error(f"failed to load policy plugin '{name}': {e}")
                raise
        return cls(policies=policies)

    def review(self, message: Message,
               client: "HiveMindClientConnection") -> Verdict:
        """Run every policy's ``review`` hook in order, applying mutations
        as we go. Returns the first deny verdict, or an allow verdict
        with the accumulated mutations already applied to ``message``.

        Policies that declare ``BYPASS_ADMIN = True`` are skipped when
        ``client.is_admin`` is truthy. Quotas / audit / rate-limiting
        policies should leave the default (``False``) so admins remain
        subject to them.
        """
        is_admin = bool(getattr(client, "is_admin", False))
        accumulated: List = []
        for policy in self.policies:
            if is_admin and getattr(type(policy), "BYPASS_ADMIN", False):
                continue
            try:
                verdict = policy.review(message, client)
            except Exception as e:
                LOG.exception(f"policy {type(policy).__name__} raised")
                return Verdict.deny("policy_error",
                                    f"{type(policy).__name__}: {e}")
            if verdict.denied:
                return verdict
            for mutation in verdict.mutations:
                try:
                    mutation.apply(message, client)
                    accumulated.append(mutation)
                except Exception as e:
                    LOG.exception("mutation application failed")
                    return Verdict.deny(
                        "policy_error",
                        f"mutation {type(mutation).__name__}: {e}",
                    )
        return Verdict.allow(*accumulated)

    def review_binary(self, payload: bytes,
                      client: "HiveMindClientConnection") -> Verdict:
        """Run every policy's ``review_binary`` hook. Mutations on a
        binary verdict are ignored (not supported); deny short-circuits.

        Same ``BYPASS_ADMIN`` semantics as :meth:`review`.
        """
        is_admin = bool(getattr(client, "is_admin", False))
        for policy in self.policies:
            if is_admin and getattr(type(policy), "BYPASS_ADMIN", False):
                continue
            try:
                verdict = policy.review_binary(payload, client)
            except Exception as e:
                LOG.exception(f"policy {type(policy).__name__} review_binary raised")
                return Verdict.deny("policy_error",
                                    f"{type(policy).__name__}: {e}")
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
        return Verdict.deny("policy_chain_unavailable", self.REASON)

    def review_binary(self, payload: bytes,
                       client: "HiveMindClientConnection") -> Verdict:
        return Verdict.deny("policy_chain_unavailable", self.REASON)


class ClientACLPolicy(PolicyPlugin):
    """Built-in admission policy enforcing the per-client ``allowed_types``
    whitelist. Always present in the chain — non-removable.

    Admins bypass via ``BYPASS_ADMIN`` (skipped at chain-runner level
    when ``client.is_admin``). Non-admin clients are denied when
    ``message.msg_type`` is not in ``client.allowed_types``. Empty
    ``allowed_types`` ⇒ deny everything (deny-by-default; the model is
    whitelist-only).

    Refreshes ``allowed_types`` from the DB on each admission so
    ``hivemind-core allow-msg`` / ``blacklist-msg`` take effect
    immediately without forcing a reconnect.

    No mutations. Agent-specific concerns (skill/intent blacklists, etc.)
    live in agent policies like ``OVOSAgentPolicy``.
    """

    BYPASS_ADMIN = True

    def review(self, message: Message,
               client: "HiveMindClientConnection") -> Verdict:
        allowed = list(getattr(client, "allowed_types", []) or [])
        db = getattr(self.hm_protocol, "db", None)
        if db is not None:
            try:
                db.sync()
                user = db.get_client_by_api_key(client.key)
                if user is not None:
                    allowed = list(getattr(user, "allowed_types", allowed) or [])
            except Exception:
                LOG.debug("ClientACLPolicy: DB refresh failed; using cached value",
                          exc_info=True)

        msg_type = getattr(message, "msg_type", None)
        if msg_type not in allowed:
            return Verdict.deny(
                "acl_disallowed_type",
                f"{msg_type} not in allowed_types",
                msg_type=msg_type,
                allowed=allowed,
            )
        return Verdict.allow()
