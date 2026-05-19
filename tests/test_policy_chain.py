"""Tests for hivemind_core.policy.PolicyChain.

Covers:
- Empty chain allows everything.
- Allow + mutations are applied to the message.
- Deny short-circuits the chain.
- Exceptions are always converted to Verdict.deny("policy_error", ...) —
  chain is unconditionally fail-closed.
- review_binary deny short-circuits.
- observe swallows exceptions.
- from_config loads plugins via PolicyPluginFactory; unknown entry
  points raise so __post_init__ can install DenyAllPolicy.
- ClientACLPolicy: allowed_types whitelist + admin bypass.
- DenyAllPolicy: rejects every admission with policy_chain_unavailable.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from hivemind_plugin_manager import Mutation, PolicyPlugin, Verdict
from ovos_bus_client.message import Message

from hivemind_core.policy import ClientACLPolicy, DenyAllPolicy, PolicyChain


class AddBlacklistedSkill(Mutation):
    """Local stand-in. The real OVOS-specific subclass lives in
    hivemind-ovos-agent-plugin now; reproducing the minimum here keeps
    these unit tests free of that runtime dep."""

    def __init__(self, skill_id: str):
        self.skill_id = skill_id

    def apply(self, message, client) -> None:
        if not isinstance(message.context, dict):
            message.context = {}
        sess = message.context.setdefault("session", {})
        if not isinstance(sess, dict):
            sess = {}
            message.context["session"] = sess
        bl = sess.setdefault("blacklisted_skills", [])
        if self.skill_id not in bl:
            bl.append(self.skill_id)


def _msg(msg_type="speak", data=None, context=None):
    return Message(msg_type, data or {}, context or {})


class _AllowPolicy(PolicyPlugin):
    def __init__(self):
        self.seen = []
        self.observed = []

    def review(self, message, client):
        self.seen.append(message.msg_type)
        return Verdict.allow()

    def observe(self, message, client):
        self.observed.append(message.msg_type)


class _MutatePolicy(PolicyPlugin):
    def review(self, message, client):
        return Verdict.allow(AddBlacklistedSkill("evil.skill"))


class _DenyPolicy(PolicyPlugin):
    def review(self, message, client):
        return Verdict.deny("quota_exceeded", "limit reached", limit=10)


class _RaisingPolicy(PolicyPlugin):
    def review(self, message, client):
        raise RuntimeError("boom")

    def observe(self, message, client):
        raise RuntimeError("observe-boom")


class _RaisingBinaryPolicy(PolicyPlugin):
    def review_binary(self, payload, client):
        raise RuntimeError("bin-boom")


class _DenyBinaryPolicy(PolicyPlugin):
    def review_binary(self, payload, client):
        return Verdict.deny("oversize")


class TestPolicyChainReview(unittest.TestCase):
    def test_empty_chain_allows(self):
        chain = PolicyChain()
        v = chain.review(_msg(), client=None)
        self.assertFalse(v.denied)

    def test_allow_applies_mutations(self):
        chain = PolicyChain(policies=[_MutatePolicy()])
        m = _msg()
        v = chain.review(m, client=None)
        self.assertFalse(v.denied)
        self.assertEqual(
            m.context["session"]["blacklisted_skills"], ["evil.skill"],
        )

    def test_deny_short_circuits(self):
        seen = _AllowPolicy()
        chain = PolicyChain(policies=[_DenyPolicy(), seen])
        v = chain.review(_msg(), client=None)
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "quota_exceeded")
        self.assertEqual(v.data, {"limit": 10})
        self.assertEqual(seen.seen, [])  # never reached

    def test_exception_always_fails_closed(self):
        chain = PolicyChain(policies=[_RaisingPolicy()])
        v = chain.review(_msg(), client=None)
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "policy_error")


class TestPolicyChainBinary(unittest.TestCase):
    def test_empty_chain_allows_binary(self):
        self.assertFalse(PolicyChain().review_binary(b"x", None).denied)

    def test_deny_binary_short_circuits(self):
        v = PolicyChain(policies=[_DenyBinaryPolicy()]).review_binary(
            b"x" * 1024, None,
        )
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "oversize")

    def test_exception_always_fails_closed_on_binary(self):
        chain = PolicyChain(policies=[_RaisingBinaryPolicy()])
        v = chain.review_binary(b"x", None)
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "policy_error")


class TestPolicyChainObserve(unittest.TestCase):
    def test_observe_runs_all_policies(self):
        p1, p2 = _AllowPolicy(), _AllowPolicy()
        PolicyChain(policies=[p1, p2]).observe(_msg("speak"), client=None)
        self.assertEqual(p1.observed, ["speak"])
        self.assertEqual(p2.observed, ["speak"])

    def test_observe_swallows_exceptions(self):
        downstream = _AllowPolicy()
        # _RaisingPolicy raises in both review and observe — but observe
        # must keep going so the downstream observer still fires.
        PolicyChain(policies=[_RaisingPolicy(), downstream]).observe(
            _msg("speak"), client=None,
        )
        self.assertEqual(downstream.observed, ["speak"])


class TestPolicyChainFromConfig(unittest.TestCase):
    def test_empty_config_yields_empty_chain(self):
        chain = PolicyChain.from_config({})
        self.assertEqual(chain.policies, [])

    def test_loads_plugins_via_factory(self):
        with patch("hivemind_core.policy.PolicyPluginFactory.create",
                   return_value=_AllowPolicy()) as create:
            chain = PolicyChain.from_config({
                "policy": {
                    "chain": [{"module": "my-policy",
                               "config": {"k": "v"}}],
                },
            }, hm_protocol="HM")
        create.assert_called_once_with("my-policy",
                                       config={"k": "v"}, hm_protocol="HM")
        self.assertEqual(len(chain.policies), 1)

    def test_load_failure_always_propagates(self):
        """No fail_open knob — chain build failures must crash startup
        so the DenyAllPolicy fallback can install."""
        with patch("hivemind_core.policy.PolicyPluginFactory.create",
                   side_effect=KeyError("missing")):
            with self.assertRaises(KeyError):
                PolicyChain.from_config({
                    "policy": {"chain": [{"module": "missing"}]},
                })

    def test_chain_entry_without_module_is_skipped(self):
        chain = PolicyChain.from_config({
            "policy": {"chain": [{"config": {}}]},
        })
        self.assertEqual(chain.policies, [])


# ---------------------------------------------------------------------------
# ClientACLPolicy — built-in allowed_types enforcement
# ---------------------------------------------------------------------------

class _FakeClient:
    def __init__(self, allowed_types=None, is_admin=False):
        self.allowed_types = list(allowed_types or [])
        self.is_admin = is_admin


class TestClientACLPolicy(unittest.TestCase):
    def test_allowed_type_allows(self):
        p = ClientACLPolicy()
        client = _FakeClient(allowed_types=["recognizer_loop:utterance"])
        v = p.review(_msg("recognizer_loop:utterance"), client)
        self.assertFalse(v.denied)
        self.assertEqual(v.mutations, [])

    def test_disallowed_type_denies(self):
        p = ClientACLPolicy()
        client = _FakeClient(allowed_types=["recognizer_loop:utterance"])
        v = p.review(_msg("speak"), client)
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "acl_disallowed_type")
        self.assertEqual(v.data["msg_type"], "speak")
        self.assertEqual(v.data["allowed"], ["recognizer_loop:utterance"])

    def test_empty_allowed_denies_everything(self):
        p = ClientACLPolicy()
        client = _FakeClient(allowed_types=[])
        v = p.review(_msg("recognizer_loop:utterance"), client)
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "acl_disallowed_type")

    def test_none_allowed_types_treated_as_empty(self):
        p = ClientACLPolicy()
        client = _FakeClient(allowed_types=None)
        v = p.review(_msg("anything"), client)
        self.assertTrue(v.denied)

    def test_reason_string_includes_msg_type(self):
        p = ClientACLPolicy()
        client = _FakeClient(allowed_types=["ok"])
        v = p.review(_msg("forbidden"), client)
        self.assertIn("forbidden", v.reason)

    def test_admin_bypasses_whitelist(self):
        p = ClientACLPolicy()
        client = _FakeClient(allowed_types=[], is_admin=True)
        v = p.review(_msg("anything"), client)
        self.assertFalse(v.denied)

    def test_db_refresh_picks_up_revoked_admin(self):
        """Mid-session admin revoke: connection cached is_admin=True,
        DB row has is_admin=False — DB wins."""
        from types import SimpleNamespace
        client = _FakeClient(allowed_types=[], is_admin=True)
        client.key = "k"
        revoked_user = SimpleNamespace(is_admin=False, allowed_types=[])
        db = MagicMock()
        db.sync = MagicMock()
        db.get_client_by_api_key = MagicMock(return_value=revoked_user)
        p = ClientACLPolicy(hm_protocol=SimpleNamespace(db=db))
        v = p.review(_msg("speak"), client)
        self.assertTrue(v.denied)

    def test_db_refresh_picks_up_granted_admin(self):
        """Reverse: connection cached is_admin=False but DB row has been
        promoted. DB wins, request is allowed."""
        from types import SimpleNamespace
        client = _FakeClient(allowed_types=[], is_admin=False)
        client.key = "k"
        promoted = SimpleNamespace(is_admin=True, allowed_types=[])
        db = MagicMock()
        db.sync = MagicMock()
        db.get_client_by_api_key = MagicMock(return_value=promoted)
        p = ClientACLPolicy(hm_protocol=SimpleNamespace(db=db))
        v = p.review(_msg("anything"), client)
        self.assertFalse(v.denied)

    def test_db_failure_falls_back_to_cached_values(self):
        """If db.sync or db.get raise, ClientACLPolicy uses the cached
        connection fields (no fail-open exception leak)."""
        from types import SimpleNamespace
        client = _FakeClient(allowed_types=["ok"], is_admin=False)
        client.key = "k"
        db = MagicMock()
        db.sync = MagicMock(side_effect=Exception("db down"))
        p = ClientACLPolicy(hm_protocol=SimpleNamespace(db=db))
        v = p.review(_msg("ok"), client)
        self.assertFalse(v.denied)  # used cached allowed_types


# ---------------------------------------------------------------------------
# DenyAllPolicy — fail-closed fallback when chain construction fails
# ---------------------------------------------------------------------------

class TestDenyAllPolicy(unittest.TestCase):
    def test_review_denies(self):
        v = DenyAllPolicy().review(_msg(), _FakeClient(allowed_types=["x"]))
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "policy_chain_unavailable")

    def test_review_binary_denies(self):
        v = DenyAllPolicy().review_binary(b"x", _FakeClient())
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "policy_chain_unavailable")


class TestFromConfigUnknownPlugin(unittest.TestCase):
    """An unknown entry-point name raises so the protocol's __post_init__
    can install the DenyAllPolicy fallback. There is no fail_open
    bypass — startup either gets the configured chain or fails closed.
    """

    def test_unknown_module_raises(self):
        with patch("hivemind_core.policy.PolicyPluginFactory.create",
                   side_effect=KeyError("missing-plugin")):
            with self.assertRaises(KeyError):
                PolicyChain.from_config({
                    "policy": {"chain": [{"module": "missing-plugin"}]},
                })


if __name__ == "__main__":
    unittest.main()
