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
    (`Verdict.deny`) or contribute mutations that are applied to the
    message before the next policy runs. Exceptions raised by any policy
    are converted to ``Verdict.deny("policy_error", ...)`` — fail-closed.
    """

    policies: List[PolicyPlugin] = field(default_factory=list)
    fail_open: bool = False  # if True, exceptions become Verdict.allow()

    @classmethod
    def from_config(cls, config: Dict[str, Any],
                    hm_protocol: Optional[Any] = None) -> "PolicyChain":
        """Build a chain from server config.

        Config shape::

            {
              "policy": {
                "fail_open": false,
                "chain": [
                  {"module": "hivemind-intent-quota-policy",
                   "config": {"limit": 100}},
                  ...
                ]
              }
            }
        """
        policy_cfg = config.get("policy") or {}
        chain_cfg = policy_cfg.get("chain") or []
        fail_open = bool(policy_cfg.get("fail_open", False))
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
                if not fail_open:
                    raise
        return cls(policies=policies, fail_open=fail_open)

    def review(self, message: Message,
               client: "HiveMindClientConnection") -> Verdict:
        """Run every policy's ``review`` hook in order, applying mutations
        as we go. Returns the first deny verdict, or an allow verdict with
        the accumulated mutations already applied to ``message``.
        """
        accumulated: List = []
        for policy in self.policies:
            try:
                verdict = policy.review(message, client)
            except Exception as e:
                LOG.exception(f"policy {type(policy).__name__} raised")
                if self.fail_open:
                    continue
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
                    if not self.fail_open:
                        return Verdict.deny(
                            "policy_error",
                            f"mutation {type(mutation).__name__}: {e}",
                        )
        return Verdict.allow(*accumulated)

    def review_binary(self, payload: bytes,
                      client: "HiveMindClientConnection") -> Verdict:
        """Run every policy's ``review_binary`` hook. Binary mutations are
        not currently supported — mutations on a binary verdict are ignored
        and logged. Deny short-circuits as usual.
        """
        for policy in self.policies:
            try:
                verdict = policy.review_binary(payload, client)
            except Exception as e:
                LOG.exception(f"policy {type(policy).__name__} review_binary raised")
                if self.fail_open:
                    continue
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


class ClientACLPolicy(PolicyPlugin):
    """Built-in admission policy enforcing the per-client ``allowed_types``
    whitelist that previously lived in
    :meth:`HiveMindClientConnection.authorize`.

    Returns ``Verdict.deny("acl_disallowed_type", ...)`` when the client's
    ``allowed_types`` list does not include the inbound message type, else
    ``Verdict.allow()``. No mutations and no DB sync — that responsibility
    moves to agent-specific policies (e.g. ``OVOSAgentPolicy`` in
    ``hivemind-ovos-agent-plugin``).
    """

    def review(self, message: Message,
               client: "HiveMindClientConnection") -> Verdict:
        allowed = list(getattr(client, "allowed_types", []) or [])
        msg_type = getattr(message, "msg_type", None)
        if msg_type not in allowed:
            return Verdict.deny(
                "acl_disallowed_type",
                f"{msg_type} not in allowed_types",
                msg_type=msg_type,
                allowed=allowed,
            )
        return Verdict.allow()
