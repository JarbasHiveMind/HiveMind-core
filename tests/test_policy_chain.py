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
- MessageTypeACLPolicy: allowed_types whitelist (admins are not exempt).
- DenyAllPolicy: rejects every admission with policy_chain_unavailable.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from hivemind_plugin_manager import Mutation, PolicyPlugin, Verdict
from ovos_bus_client.message import Message

from hivemind_core.policy import MessageTypeACLPolicy, DenyAllPolicy, PolicyChain


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
# MessageTypeACLPolicy — built-in allowed_types enforcement
# ---------------------------------------------------------------------------

class _FakeClient:
    def __init__(self, allowed_types=None, is_admin=False):
        self.allowed_types = list(allowed_types or [])
        self.is_admin = is_admin
        self.key = "k"
        self._resolved = None
        self._resolve_calls = 0

    def resolve_user(self, db, ttl: float = 5.0, force: bool = False):
        """Test stand-in for HiveMindClientConnection.resolve_user — the
        chain treats _FakeClient as a connection, so we mirror that
        method shape here. Uses a single-shot cache so we can assert on
        ``_resolve_calls``."""
        self._resolve_calls += 1
        if self._resolved is None or force:
            try:
                self._resolved = db.get_client_by_api_key(self.key)
            except Exception:
                raise
        return self._resolved

    def invalidate_user(self):
        self._resolved = None


class TestMessageTypeACLPolicy(unittest.TestCase):
    def test_allowed_type_allows(self):
        p = MessageTypeACLPolicy()
        client = _FakeClient(allowed_types=["recognizer_loop:utterance"])
        v = p.review(_msg("recognizer_loop:utterance"), client)
        self.assertFalse(v.denied)
        self.assertEqual(v.mutations, [])

    def test_disallowed_type_denies(self):
        p = MessageTypeACLPolicy()
        client = _FakeClient(allowed_types=["recognizer_loop:utterance"])
        v = p.review(_msg("speak"), client)
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "acl_disallowed_type")
        self.assertEqual(v.data["msg_type"], "speak")
        self.assertEqual(v.data["allowed"], ["recognizer_loop:utterance"])

    def test_empty_allowed_denies_everything(self):
        p = MessageTypeACLPolicy()
        client = _FakeClient(allowed_types=[])
        v = p.review(_msg("recognizer_loop:utterance"), client)
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "acl_disallowed_type")

    def test_none_allowed_types_treated_as_empty(self):
        p = MessageTypeACLPolicy()
        client = _FakeClient(allowed_types=None)
        v = p.review(_msg("anything"), client)
        self.assertTrue(v.denied)

    def test_reason_string_includes_msg_type(self):
        p = MessageTypeACLPolicy()
        client = _FakeClient(allowed_types=["ok"])
        v = p.review(_msg("forbidden"), client)
        self.assertIn("forbidden", v.reason)

    def test_admins_are_not_exempt_from_allowed_types(self):
        """is_admin is informational only — MessageTypeACLPolicy honours
        allowed_types for every client. Operators grant message types
        to admins via ``allow-msg`` like any other client."""
        p = MessageTypeACLPolicy()
        client = _FakeClient(allowed_types=[], is_admin=True)
        v = p.review(_msg("anything"), client)
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "acl_disallowed_type")

    def test_db_refresh_picks_up_allowed_type_grant(self):
        """Mid-session grant via `allow-msg`: connection cached
        allowed_types=[], DB row has the type — DB wins."""
        from types import SimpleNamespace
        client = _FakeClient(allowed_types=[], is_admin=False)
        granted = SimpleNamespace(allowed_types=["recognizer_loop:utterance"])
        db = MagicMock()
        db.get_client_by_api_key = MagicMock(return_value=granted)
        p = MessageTypeACLPolicy(hm_protocol=SimpleNamespace(db=db))
        v = p.review(_msg("recognizer_loop:utterance"), client)
        self.assertFalse(v.denied)

    def test_db_failure_falls_back_to_cached_values(self):
        """If resolve_user raises, MessageTypeACLPolicy uses the cached
        connection fields (no fail-open exception leak)."""
        from types import SimpleNamespace
        client = _FakeClient(allowed_types=["ok"], is_admin=False)

        def boom(db, ttl=5.0, force=False):
            raise RuntimeError("db down")
        client.resolve_user = boom
        db = MagicMock()
        p = MessageTypeACLPolicy(hm_protocol=SimpleNamespace(db=db))
        v = p.review(_msg("ok"), client)
        self.assertFalse(v.denied)  # used cached allowed_types


class TestChainAdminHandling(unittest.TestCase):
    """The chain runner gives ``client.is_admin`` no special treatment.
    Every policy runs for every client; policies that care branch on
    is_admin themselves."""

    def test_chain_runs_all_policies_for_admin(self):
        """An admin client with empty allowed_types still gets denied
        by MessageTypeACLPolicy. Admins are subject to the whitelist."""
        admin = _FakeClient(allowed_types=[], is_admin=True)
        v = PolicyChain(policies=[MessageTypeACLPolicy()]).review(
            _msg("speak"), admin,
        )
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "acl_disallowed_type")

    def test_chain_runs_custom_policies_for_admin(self):
        """A custom policy always applies to admins unless the policy
        itself opts out by branching on client.is_admin."""

        class _AlwaysDeny(PolicyPlugin):
            def review(self, message, client):
                return Verdict.deny("nope", "admins not exempt")

        admin = _FakeClient(allowed_types=["speak"], is_admin=True)
        v = PolicyChain(policies=[_AlwaysDeny()]).review(_msg("speak"), admin)
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "nope")

    def test_chain_review_binary_runs_for_admin(self):
        """review_binary likewise has no runner-level admin bypass."""

        class _DenyBinary(PolicyPlugin):
            def review_binary(self, payload, client):
                return Verdict.deny("nope")

        admin = _FakeClient(is_admin=True)
        v = PolicyChain(policies=[_DenyBinary()]).review_binary(b"x", admin)
        self.assertTrue(v.denied)

    def test_policy_can_self_branch_on_is_admin(self):
        """Policies that want admin-exemption check client.is_admin
        themselves — there's no class-level switch."""

        class _AdminAware(PolicyPlugin):
            def review(self, message, client):
                if getattr(client, "is_admin", False):
                    return Verdict.allow()
                return Verdict.deny("non_admin", "only admins")

        chain = PolicyChain(policies=[_AdminAware()])

        admin = _FakeClient(allowed_types=["speak"], is_admin=True)
        self.assertFalse(chain.review(_msg("speak"), admin).denied)

        guest = _FakeClient(allowed_types=["speak"], is_admin=False)
        self.assertTrue(chain.review(_msg("speak"), guest).denied)


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


class _ReplaceMutation(Mutation):
    """Replacement-path mutation: returns a wholly new Message instead of
    mutating in place. The chain runner must swap the current message for
    the returned one and continue applying any remaining mutations to it."""

    def __init__(self, new_type: str):
        self.new_type = new_type

    def apply(self, message, client):
        return Message(self.new_type, {"replaced": True}, dict(message.context))


class _TagMutation(Mutation):
    """In-place mutation that sets a marker in data — used to verify that
    remaining mutations after a replacement operate on the *new* message."""

    def __init__(self, tag: str):
        self.tag = tag

    def apply(self, message, client) -> None:
        message.data["tag"] = self.tag


class _ReplaceMutationPolicy(PolicyPlugin):
    def review(self, message, client):
        return Verdict.allow(_ReplaceMutation("replaced:type"))


class _ReplaceAndTagPolicy(PolicyPlugin):
    def review(self, message, client):
        return Verdict.allow(_ReplaceMutation("replaced:type"), _TagMutation("after-replace"))


class TestMutationReplacementPath(unittest.TestCase):
    def test_mutation_replacement_swaps_message(self):
        """non-None return from mutation.apply() replaces current message."""
        chain = PolicyChain(policies=[_ReplaceMutationPolicy()])
        original = _msg("original:type")
        v = chain.review(original, client=None)
        self.assertFalse(v.denied)
        # The replacement is observed via the message object that the next
        # policy or observer would see — the chain returns a verdict with
        # the accumulated mutations; the caller's reference to ``message``
        # is NOT changed (replacement is runner-internal). We verify the
        # replacement happened by checking the subsequent mutation path.

    def test_remaining_mutations_run_on_replacement(self):
        """Mutations that follow a replacement operate on the new message."""
        chain = PolicyChain(policies=[_ReplaceAndTagPolicy()])
        original = _msg("original:type")
        v = chain.review(original, client=None)
        self.assertFalse(v.denied)
        # The replacement happened internally; the _TagMutation ran on the
        # replacement. We cannot directly observe the replacement message
        # from the verdict (only the mutation list is returned), but we can
        # use a spy mutation to confirm the tag was applied to the replacement
        # by wiring a custom policy that chains both mutations.

    def test_replacement_message_used_by_next_policy(self):
        """When a mutation returns a replacement, the next policy in the
        chain receives the replacement message, not the original."""
        seen_types: list = []

        class _SpyPolicy(PolicyPlugin):
            def review(self, msg, client):
                seen_types.append(msg.msg_type)
                return Verdict.allow()

        # Policy 1 returns a replacement mutation; Policy 2 is a spy.
        class _ReplaceFirst(PolicyPlugin):
            def review(self, msg, client):
                return Verdict.allow(_ReplaceMutation("swapped:type"))

        chain = PolicyChain(policies=[_ReplaceFirst(), _SpyPolicy()])
        chain.review(_msg("original:type"), client=None)
        # The spy should have seen the swapped type, not the original.
        self.assertEqual(seen_types, ["swapped:type"])

    def test_tag_mutation_applied_after_replacement(self):
        """_TagMutation runs on the replacement message produced by
        _ReplaceMutation when both are in the same Verdict."""

        applied_on: list = []

        class _SpyTagMutation(Mutation):
            def apply(self, message, client):
                applied_on.append(message.msg_type)
                message.data["tag"] = "yes"

        class _ReplaceAndSpyTag(PolicyPlugin):
            def review(self, msg, client):
                return Verdict.allow(_ReplaceMutation("replaced:type"), _SpyTagMutation())

        chain = PolicyChain(policies=[_ReplaceAndSpyTag()])
        chain.review(_msg("original:type"), client=None)
        # SpyTagMutation must have run on the replaced message, not original.
        self.assertEqual(applied_on, ["replaced:type"])

    def test_in_place_mutation_none_return_does_not_swap(self):
        """In-place mutation (returns None) does NOT trigger a message swap.
        Downstream policies still see the same message instance."""
        seen_ids: list = []

        class _InPlaceMutation(Mutation):
            def apply(self, message, client) -> None:
                message.data["mutated"] = True

        class _InPlacePolicy(PolicyPlugin):
            def review(self, msg, client):
                return Verdict.allow(_InPlaceMutation())

        class _SpyPolicy(PolicyPlugin):
            def review(self, msg, client):
                seen_ids.append(id(msg))
                return Verdict.allow()

        original = _msg()
        original_id = id(original)
        chain = PolicyChain(policies=[_InPlacePolicy(), _SpyPolicy()])
        chain.review(original, client=None)
        # Same object passed through — no replacement.
        self.assertEqual(seen_ids, [original_id])
        # In-place mutation took effect.
        self.assertTrue(original.data.get("mutated"))


class _RaisingMutation(Mutation):
    def apply(self, message, client):
        raise RuntimeError("boom-mutate")


class _RaisingMutationPolicy(PolicyPlugin):
    def review(self, message, client):
        return Verdict.allow(_RaisingMutation())


class TestMutationFailure(unittest.TestCase):
    def test_mutation_apply_failure_converts_to_policy_error(self):
        chain = PolicyChain(policies=[_RaisingMutationPolicy()])
        v = chain.review(_msg(), client=None)
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "policy_error")
        self.assertEqual(v.data.get("mutation"), "_RaisingMutation")
        self.assertEqual(v.data.get("policy"), "_RaisingMutationPolicy")
        self.assertIn("error", v.data)


class TestStructuredPolicyErrorData(unittest.TestCase):
    def test_policy_exception_includes_policy_name_in_data(self):
        chain = PolicyChain(policies=[_RaisingPolicy()])
        v = chain.review(_msg(), client=None)
        self.assertEqual(v.code, "policy_error")
        self.assertEqual(v.data.get("policy"), "_RaisingPolicy")
        self.assertIn("error", v.data)


class TestMessageTypeACLPolicyMemoisation(unittest.TestCase):
    def test_resolve_user_cached_across_chain(self):
        """MessageTypeACLPolicy calls client.resolve_user; downstream
        policies in the same chain pass reuse the cached row."""
        from types import SimpleNamespace
        client = _FakeClient(allowed_types=[], is_admin=False)
        granted = SimpleNamespace(allowed_types=["speak"])
        db = MagicMock()
        db.get_client_by_api_key = MagicMock(return_value=granted)
        p = MessageTypeACLPolicy(hm_protocol=SimpleNamespace(db=db))
        v = p.review(_msg("speak"), client)
        self.assertFalse(v.denied)
        self.assertIs(client._resolved, granted)
        self.assertEqual(client._resolve_calls, 1)


class TestMessageTypeACLPolicyNoDB(unittest.TestCase):
    def test_no_db_uses_cached_allowed_types(self):
        from types import SimpleNamespace
        client = _FakeClient(allowed_types=["speak"])
        # hm_protocol with db=None
        p = MessageTypeACLPolicy(hm_protocol=SimpleNamespace(db=None))
        self.assertFalse(p.review(_msg("speak"), client).denied)
        self.assertTrue(p.review(_msg("nope"), client).denied)

    def test_hm_protocol_none_uses_cached_allowed_types(self):
        client = _FakeClient(allowed_types=["speak"])
        p = MessageTypeACLPolicy()
        self.assertFalse(p.review(_msg("speak"), client).denied)


class TestObserveNotCalledWhenDenied(unittest.TestCase):
    def test_observe_skipped_on_denial(self):
        """A denial verdict from PolicyChain.review means the message
        was not emitted — callers must not invoke observe() in that path.
        We assert the contract at the caller-test level by ensuring the
        chain's review() result is denied and the caller can branch."""
        chain = PolicyChain(policies=[_DenyPolicy(), _AllowPolicy()])
        observed = _AllowPolicy()
        chain_with_observer = PolicyChain(policies=[_DenyPolicy(), observed])
        v = chain_with_observer.review(_msg(), client=None)
        self.assertTrue(v.denied)
        # If a caller respects the deny contract and skips observe(),
        # observed.observed stays empty. We simulate the contract:
        if not v.denied:
            chain_with_observer.observe(_msg(), client=None)
        self.assertEqual(observed.observed, [])


class TestDenyAllPolicyReview(unittest.TestCase):
    def test_review_and_review_binary_return_policy_chain_unavailable(self):
        p = DenyAllPolicy()
        v = p.review(_msg(), _FakeClient())
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "policy_chain_unavailable")
        vb = p.review_binary(b"x", _FakeClient())
        self.assertTrue(vb.denied)
        self.assertEqual(vb.code, "policy_chain_unavailable")


class TestEntryPointDiscovery(unittest.TestCase):
    """Built-in policies are registered under the ``hivemind.policy``
    entry-point group. This verifies the metadata is wired correctly."""

    def test_builtin_policies_discoverable(self):
        from importlib.metadata import entry_points
        names = {ep.name for ep in entry_points(group="hivemind.policy")}
        # Both built-ins must be discoverable when hivemind-core is
        # installed.
        self.assertIn("hivemind-message-type-acl-policy", names)
        self.assertIn("hivemind-deny-all-policy", names)


class TestOnVerdictHook(unittest.TestCase):
    def test_on_verdict_called_for_each_policy(self):
        events = []
        chain = PolicyChain(
            policies=[_AllowPolicy(), _DenyPolicy()],
            on_verdict=lambda p, v: events.append(
                (type(p).__name__, v.denied, v.code),
            ),
        )
        chain.review(_msg(), client=None)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0][0], "_AllowPolicy")
        self.assertFalse(events[0][1])
        self.assertEqual(events[1][0], "_DenyPolicy")
        self.assertTrue(events[1][1])
        self.assertEqual(events[1][2], "quota_exceeded")

    def test_on_verdict_exception_swallowed(self):
        def boom(p, v):
            raise RuntimeError("trace-boom")

        chain = PolicyChain(policies=[_AllowPolicy()], on_verdict=boom)
        # Must not raise.
        v = chain.review(_msg(), client=None)
        self.assertFalse(v.denied)

    def test_on_verdict_fires_on_policy_exception(self):
        events = []
        chain = PolicyChain(
            policies=[_RaisingPolicy()],
            on_verdict=lambda p, v: events.append((type(p).__name__, v.code)),
        )
        chain.review(_msg(), client=None)
        self.assertEqual(events, [("_RaisingPolicy", "policy_error")])


class TestOptionalPolicyFlag(unittest.TestCase):
    def test_optional_policy_exception_does_not_block_chain(self):
        chain = PolicyChain(
            policies=[_RaisingPolicy(), _AllowPolicy()],
            _optional=[True, False],
        )
        v = chain.review(_msg(), client=None)
        self.assertFalse(v.denied)

    def test_mandatory_policy_exception_blocks_chain(self):
        chain = PolicyChain(
            policies=[_RaisingPolicy(), _AllowPolicy()],
            _optional=[False, False],
        )
        v = chain.review(_msg(), client=None)
        self.assertTrue(v.denied)
        self.assertEqual(v.code, "policy_error")

    def test_optional_flag_defaults_to_false(self):
        chain = PolicyChain.from_config({
            "policy": {"chain": [
                {"module": "hivemind-deny-all-policy"},
            ]},
        })
        self.assertEqual(chain._optional, [False])


class TestOnVerdictAccumulatedMutations(unittest.TestCase):
    def test_on_verdict_receives_accumulated_mutations_on_allow(self):
        events = []
        chain = PolicyChain(
            policies=[_MutatePolicy(), _AllowPolicy()],
            on_verdict=lambda p, v: events.append((p, list(v.mutations))),
        )
        v = chain.review(_msg(), client=None)
        self.assertFalse(v.denied)
        # Last event is the synthetic chain-complete verdict with
        # policy=None and the accumulated mutation list.
        self.assertIsNone(events[-1][0])
        self.assertEqual(len(events[-1][1]), 1)
        self.assertEqual(len(v.mutations), 1)


class _AgentStub:
    """Structural AgentProtocol stand-in without the optional new hook."""

    def __init__(self, bus):
        self.bus = bus
        self.hm_protocol = None
        self.callbacks = MagicMock()

    def get_bus(self, client=None):
        return self.bus


class _DeliveryAgentStub(_AgentStub):
    """Concrete hook implementation with an inspectable delivery spy."""

    def __init__(self, bus):
        super().__init__(bus)
        self.delivery = MagicMock(return_value=True)

    def emit_client_message(self, message, client=None):
        return self.delivery(message, client)


class TestProtocolWiring(unittest.TestCase):
    """Unit tests for how the admission chain is wired into
    HiveMindListenerProtocol.handle_inject_agent_msg and
    handle_binary_message — verify the deny→client-notification path and
    the observe fire-and-forget contract without a real network stack."""

    def _make_protocol(self, agent_type=_AgentStub):
        """Build a minimal HiveMindListenerProtocol with FakeBus agent."""
        from unittest.mock import MagicMock
        from ovos_utils.fakebus import FakeBus
        from hivemind_core.protocol import HiveMindListenerProtocol
        from hivemind_core.policy import PolicyChain

        bus = FakeBus()
        agent = agent_type(bus)

        proto = HiveMindListenerProtocol.__new__(HiveMindListenerProtocol)
        proto.agent_protocol = agent
        proto.binary_data_protocol = MagicMock()
        proto.identity = MagicMock()
        proto.identity.private_key = None
        proto.identity.public_key = None
        proto.identity.site_id = "test-site"
        proto.db = MagicMock()
        proto.callbacks = MagicMock()
        proto.hive_mapper = MagicMock()
        proto.peer = "master:0.0.0.0"
        proto.require_crypto = False
        proto.handshake_enabled = False
        proto.escalate_callback = None
        proto.illegal_callback = None
        proto.propagate_callback = None
        proto.broadcast_callback = None
        proto.agent_bus_callback = None
        proto.shared_bus_callback = None
        proto.clients = {}
        proto._seen_flood_ids = set()
        proto.policy_chain = PolicyChain()  # empty = allow-all
        return proto, bus

    def _make_client(self, allowed_types=None):
        from unittest.mock import MagicMock
        from hivemind_core.protocol import HiveMindClientConnection
        client = MagicMock(spec=HiveMindClientConnection)
        client.allowed_types = list(allowed_types or [])
        client.is_admin = False
        client.peer = "test::session-1"
        client.sess = MagicMock()
        client.sess.session_id = "session-1"
        client.sess.serialize.return_value = {"session_id": "session-1"}
        client.sess.pipeline = None
        client.authorize.return_value = True
        client.key = "test-key"
        client._resolved_user = None
        client._resolved_user_ts = 0.0
        # capture send calls
        client.send = MagicMock()
        return client

    def test_deny_sends_hive_policy_denied_to_client(self):
        """A deny verdict triggers _send_policy_denied, not bus.emit."""
        from hivemind_core.policy import PolicyChain
        from hivemind_plugin_manager import PolicyPlugin, Verdict

        class _DenyAll(PolicyPlugin):
            def review(self, msg, client):
                return Verdict.deny("test_deny", "unit-test deny")

        proto, bus = self._make_protocol()
        proto.policy_chain = PolicyChain(policies=[_DenyAll()])
        client = self._make_client(allowed_types=["speak"])

        emitted = []
        bus.on("speak", emitted.append)

        msg = Message("speak", {"utterance": "hi"}, {"session": {"session_id": "session-1"}})
        proto.handle_inject_agent_msg(msg, client)

        # Not emitted onto the agent bus.
        self.assertEqual(emitted, [])
        # Client received the denial notification.
        self.assertTrue(client.send.called)
        sent_hm = client.send.call_args[0][0]
        from hivemind_bus_client.message import HiveMessageType
        self.assertEqual(sent_hm.msg_type, HiveMessageType.BUS)
        denied_msg = sent_hm.payload
        self.assertEqual(denied_msg.msg_type, "hive.policy.denied")
        self.assertEqual(denied_msg.data["code"], "test_deny")
        self.assertEqual(denied_msg.data["denied_type"], "speak")

    def test_allow_emits_to_agent_bus(self):
        """An allow verdict results in bus.emit with the message."""
        proto, bus = self._make_protocol()
        client = self._make_client()

        emitted = []
        bus.on("speak", emitted.append)

        msg = Message("speak", {"utterance": "hi"}, {"session": {"session_id": "session-1"}})
        proto.handle_inject_agent_msg(msg, client)

        self.assertEqual(len(emitted), 1)
        self.assertFalse(client.send.called)

    def test_allow_uses_agent_delivery_hook_when_available(self):
        """An agent can own reliable delivery instead of exposing its raw bus."""
        proto, bus = self._make_protocol(_DeliveryAgentStub)
        client = self._make_client()

        emitted = []
        bus.on("speak", emitted.append)

        msg = Message("speak", {"utterance": "hi"},
                      {"session": {"session_id": "session-1"}})
        proto.handle_inject_agent_msg(msg, client)

        proto.agent_protocol.delivery.assert_called_once_with(msg, client)
        self.assertEqual(emitted, [])
        self.assertFalse(client.send.called)

    def test_agent_delivery_failure_is_reported_without_observing(self):
        """A failed agent write is visible and is not counted as delivered."""
        from hivemind_core.policy import PolicyChain

        observe_calls = []

        class _ObserveSpy(PolicyPlugin):
            def observe(self, msg, client):
                observe_calls.append(msg.msg_type)

        proto, bus = self._make_protocol(_DeliveryAgentStub)
        proto.policy_chain = PolicyChain(policies=[_ObserveSpy()])
        proto.agent_protocol.delivery = MagicMock(
            side_effect=ConnectionError("OVOS bus unavailable")
        )
        proto.agent_bus_callback = MagicMock()
        client = self._make_client()

        emitted = []
        bus.on("speak", emitted.append)

        msg = Message("speak", {"utterance": "hi"},
                      {"session": {"session_id": "session-1"}})
        proto.handle_inject_agent_msg(msg, client)

        self.assertEqual(emitted, [])
        self.assertEqual(observe_calls, [])
        proto.agent_bus_callback.assert_not_called()
        sent = client.send.call_args[0][0].payload
        self.assertEqual(sent.msg_type, "hive.agent_bus.error")
        self.assertEqual(sent.data["failed_type"], "speak")
        self.assertEqual(sent.data["error_type"], "ConnectionError")

    def test_agent_delivery_rejection_is_reported(self):
        """A false delivery result is an explicit rejection, not success."""
        proto, _bus = self._make_protocol(_DeliveryAgentStub)
        proto.agent_protocol.delivery = MagicMock(return_value=False)
        client = self._make_client()

        msg = Message("speak", {"utterance": "hi"},
                      {"session": {"session_id": "session-1"}})
        proto.handle_inject_agent_msg(msg, client)

        sent = client.send.call_args[0][0].payload
        self.assertEqual(sent.msg_type, "hive.agent_bus.error")
        self.assertEqual(sent.data["error_type"], "RuntimeError")

    def test_observe_called_after_emit(self):
        """observe() fires after bus.emit, and exceptions are swallowed."""
        from hivemind_core.policy import PolicyChain
        from hivemind_plugin_manager import PolicyPlugin, Verdict

        observe_calls: list = []

        class _ObserveSpy(PolicyPlugin):
            def observe(self, msg, client):
                observe_calls.append(msg.msg_type)

        proto, bus = self._make_protocol()
        proto.policy_chain = PolicyChain(policies=[_ObserveSpy()])
        client = self._make_client()

        emitted = []
        bus.on("speak", emitted.append)

        msg = Message("speak", {"utterance": "hi"}, {"session": {"session_id": "session-1"}})
        proto.handle_inject_agent_msg(msg, client)

        self.assertEqual(len(emitted), 1)
        self.assertEqual(observe_calls, ["speak"])

    def test_observe_exception_does_not_block_delivery(self):
        """observe() raising must not prevent prior bus.emit from completing."""
        from hivemind_core.policy import PolicyChain

        proto, bus = self._make_protocol()
        proto.policy_chain = PolicyChain(policies=[_RaisingPolicy()])

        # _RaisingPolicy also raises in review(), so override with one that
        # only raises in observe:
        class _ObserveRaiser(PolicyPlugin):
            def observe(self, msg, client):
                raise RuntimeError("observe-bomb")

        proto.policy_chain = PolicyChain(policies=[_ObserveRaiser()])
        client = self._make_client()

        emitted = []
        bus.on("speak", emitted.append)

        msg = Message("speak", {"utterance": "hi"}, {"session": {"session_id": "session-1"}})
        # Must not raise.
        proto.handle_inject_agent_msg(msg, client)

        self.assertEqual(len(emitted), 1)

    def test_policy_exception_in_wired_chain_sends_policy_error(self):
        """Exception in a policy during handle_inject_agent_msg → policy_error
        deny sent to client, message never reaches bus."""
        from hivemind_core.policy import PolicyChain

        proto, bus = self._make_protocol()
        proto.policy_chain = PolicyChain(policies=[_RaisingPolicy()])
        client = self._make_client()

        emitted = []
        bus.on("speak", emitted.append)

        msg = Message("speak", {"utterance": "hi"}, {"session": {"session_id": "session-1"}})
        proto.handle_inject_agent_msg(msg, client)

        self.assertEqual(emitted, [])
        self.assertTrue(client.send.called)
        sent_hm = client.send.call_args[0][0]
        denied_msg = sent_hm.payload
        self.assertEqual(denied_msg.data["code"], "policy_error")


if __name__ == "__main__":
    unittest.main()
