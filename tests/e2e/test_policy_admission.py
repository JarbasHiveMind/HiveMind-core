"""End-to-end coverage for the policy admission chain (#85).

Exercises the chain through a real master/satellite stack via hivescope:

- MessageTypeACLPolicy (built-in, ``allowed_types`` enforcement) replaces the
  static check that used to live in ``HiveMindClientConnection.authorize``.
- OVOSAgentPolicy (from ``hivemind-ovos-agent-plugin``) replaces the
  side-effecting skill/intent/msg blacklist injection that used to live
  in ``HiveMindListenerProtocol._update_blacklist``.

These tests are the backwards-compat lock for the migration — every
observable that downstream OVOS components rely on (session blacklists,
silent drop of disallowed types, send-side msg blacklist) must look
identical to the pre-migration behaviour.

CI installs ``hivemind-plugin-manager`` from ``feat/policy-plugins`` and
``hivemind-ovos-agent-plugin`` from ``feat/ovos-agent-policy`` so the
entry points resolve. See ``.github/workflows/build_tests.yml``.
"""
from __future__ import annotations

import time

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from hivescope.topology import TopologyBuilder


def _wait_for(condition, timeout: float = 2.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


def _capture_denied(satellite):
    """Subscribe to ``hive.policy.denied`` notifications on the satellite.

    Delivered as a BUS-wrapped ``Message`` with type ``hive.policy.denied``.
    Returns a list that the caller can assert on once the message arrives.
    """
    captured: list = []

    def _on(msg):
        payload = getattr(msg, "payload", None)
        if isinstance(payload, Message) and payload.msg_type == "hive.policy.denied":
            captured.append(payload)

    satellite.shim.emitter.on(HiveMessageType.BUS, _on)
    return captured


def _build(allowed_types=None, skill_bl=None, intent_bl=None):
    """Build a topology where the satellite registers under its own
    auto-generated access_key (not a pre-chosen one), so the live DB row
    matches the connection key. Pass per-client ACL fields through
    ``add_satellite`` — they're forwarded to ``SatelliteNode.connect()``
    which calls ``master.register_satellite(key=identity.access_key, ...)``.
    """
    b = TopologyBuilder()
    m = b.add_master("M0")
    b.add_satellite(
        "S0", upstream=m,
        allowed_types=allowed_types,
        skill_blacklist=skill_bl,
        intent_blacklist=intent_bl,
    )
    return b, m


def _swap_chain(master, configured_entries):
    """Replace the in-memory policy chain on an already-built master.

    Mirrors ``HiveMindListenerProtocol.__post_init__`` semantics:
    always prepends the non-removable built-ins (MessageTypeACLPolicy,
    DefaultSessionPolicy) to the configured chain, so the allowed_types
    whitelist and the reserved-session gate are never bypassable.
    """
    from hivemind_core.policy import (DefaultSessionPolicy,
                                      MessageTypeACLPolicy, PolicyChain)
    chain = PolicyChain.from_config(
        {"policy": {"chain": configured_entries}},
        hm_protocol=master.hm_protocol,
    )
    builtins = (MessageTypeACLPolicy, DefaultSessionPolicy)
    configured = [p for p in chain.policies if not isinstance(p, builtins)]
    master.hm_protocol.policy_chain = PolicyChain(
        policies=[MessageTypeACLPolicy(hm_protocol=master.hm_protocol),
                  DefaultSessionPolicy(hm_protocol=master.hm_protocol),
                  *configured],
    )


def _ctx(satellite):
    """Build a satellite-side message context with a real session.

    Required for non-admin satellites because the master rejects bus
    messages whose ``session_id == "default"``.
    """
    sess = Session(session_id=satellite.shim.session_id,
                   site_id="client-site")
    return {"session": sess.serialize()}


def _send_utterance(satellite, text="hi", msg_type="recognizer_loop:utterance"):
    satellite.send(HiveMessage(
        HiveMessageType.BUS,
        payload=Message(msg_type, {"utterances": [text]}, _ctx(satellite)),
    ))


def _send_speak(satellite, text="blocked"):
    satellite.send(HiveMessage(
        HiveMessageType.BUS,
        payload=Message("speak", {"utterance": text}, _ctx(satellite)),
    ))


# ---------------------------------------------------------------------------
# MessageTypeACLPolicy — allowed_types
# ---------------------------------------------------------------------------

def test_disallowed_type_is_denied_and_notifies_client():
    """A type not in allowed_types is dropped and a hive.policy.denied
    notification is delivered to the satellite. **New observable** vs
    the old silent-drop in authorize()."""
    b, m = _build(allowed_types=["recognizer_loop:utterance"])
    try:
        b.start_all()
        s = b.get_satellite("S0")
        _swap_chain(m, [])

        emitted = []
        m.agent_protocol.bus.on("speak", emitted.append)

        denied = _capture_denied(s)

        _send_speak(s)

        assert _wait_for(lambda: len(denied) >= 1), (
            f"satellite did not receive hive.policy.denied: {denied}"
        )
        # never injected onto agent bus
        assert emitted == [], f"disallowed 'speak' leaked onto agent bus: {emitted}"
        assert denied[0].data["code"] == "acl_disallowed_type"
        assert denied[0].data["denied_type"] == "speak"
    finally:
        b.stop_all()


def test_allowed_type_is_admitted():
    b, m = _build(allowed_types=["recognizer_loop:utterance"])
    try:
        b.start_all()
        s = b.get_satellite("S0")
        _swap_chain(m, [])

        seen = []
        m.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)

        _send_utterance(s)

        assert _wait_for(lambda: len(seen) >= 1), (
            f"allowed message did not reach agent bus: {seen}"
        )
    finally:
        b.stop_all()


def test_empty_allowed_types_denies_all():
    """MessageTypeACLPolicy is always prepended and cannot be removed. Empty
    allowed_types ⇒ everything is denied, even with an otherwise-empty
    configured chain."""
    b, m = _build(allowed_types=[])
    try:
        b.start_all()
        s = b.get_satellite("S0")
        _swap_chain(m, [])

        seen = []
        m.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)
        denied = _capture_denied(s)

        _send_utterance(s)

        assert _wait_for(lambda: len(denied) >= 1), denied
        assert seen == [], seen
        assert denied[0].data["code"] == "acl_disallowed_type"
    finally:
        b.stop_all()


# ---------------------------------------------------------------------------
# OVOSAgentPolicy — skill/intent blacklist injection (backwards-compat lock)
# ---------------------------------------------------------------------------

def test_skill_blacklist_injected_into_session():
    """Matches the legacy ``_update_blacklist`` behaviour: skills listed
    on the client row appear in ``message.context["session"]["blacklisted_skills"]``
    on the agent bus."""
    b, m = _build(allowed_types=["recognizer_loop:utterance"],
                  skill_bl=["weather.skill", "news.skill"])
    try:
        b.start_all()
        s = b.get_satellite("S0")
        _swap_chain(m, [{"module": "hivemind-ovos-agent-policy"}])

        seen = []
        m.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)

        _send_utterance(s)

        assert _wait_for(lambda: len(seen) >= 1)
        injected = seen[-1].context.get("session", {}).get("blacklisted_skills", [])
        assert "weather.skill" in injected, injected
        assert "news.skill" in injected, injected
    finally:
        b.stop_all()


def test_intent_blacklist_injected_into_session():
    b, m = _build(allowed_types=["recognizer_loop:utterance"],
                  intent_bl=["weather:WeatherIntent"])
    try:
        b.start_all()
        s = b.get_satellite("S0")
        _swap_chain(m, [{"module": "hivemind-ovos-agent-policy"}])

        seen = []
        m.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)

        _send_utterance(s)

        assert _wait_for(lambda: len(seen) >= 1)
        injected = seen[-1].context.get("session", {}).get("blacklisted_intents", [])
        assert "weather:WeatherIntent" in injected, injected
    finally:
        b.stop_all()


def test_db_changes_picked_up_between_messages():
    """Backwards-compat lock for the old ``self.db.sync()`` behaviour:
    updating a client row mid-session takes effect on the next message
    without restart.

    Uses a unique skill name to avoid contamination from any other test
    that adds well-known skill names — OVOS Session defaults are
    process-global.
    """
    unique = "e2e-policy-db-sync.test"
    b, m = _build(allowed_types=["recognizer_loop:utterance"])
    try:
        b.start_all()
        s = b.get_satellite("S0")
        _swap_chain(m, [{"module": "hivemind-ovos-agent-policy"}])

        seen = []
        m.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)

        # First message: unique skill not present.
        _send_utterance(s, "first")
        assert _wait_for(lambda: len(seen) >= 1)
        bl1 = seen[-1].context.get("session", {}).get("blacklisted_skills", [])
        assert unique not in bl1, bl1

        # Mutate the existing DB row for this satellite (keyed by the
        # access_key the handshake registered under). add_client() updates
        # in place when the row already exists.
        m.db.add_client(
            name="test-satellite",
            key=s.identity.access_key,
            password=s.identity.password,
            allowed_types=["recognizer_loop:utterance"],
            skill_blacklist=[unique],
        )
        _send_utterance(s, "second")
        assert _wait_for(lambda: len(seen) >= 2)
        bl2 = seen[-1].context.get("session", {}).get("blacklisted_skills", [])
        assert unique in bl2, (
            f"db.sync() didn't pick up the new blacklist: {bl2}"
        )
    finally:
        b.stop_all()


# ---------------------------------------------------------------------------
# Fail-closed semantics
# ---------------------------------------------------------------------------

def test_missing_plugin_falls_back_to_deny_all():
    """A configured policy entry-point that fails to resolve installs
    the DenyAllPolicy fallback rather than silently allowing traffic.
    Verifies the always-fail-closed contract in
    HiveMindListenerProtocol.__post_init__.
    """
    from hivemind_core.policy import DenyAllPolicy, PolicyChain

    b, m = _build(allowed_types=["recognizer_loop:utterance"])
    try:
        b.start_all()
        s = b.get_satellite("S0")

        # from_config must raise on a missing entry point — no silent skip.
        try:
            PolicyChain.from_config({
                "policy": {"chain": [{"module": "does-not-exist-policy"}]},
            }, hm_protocol=m.hm_protocol)
            raised = False
        except Exception:
            raised = True
        assert raised, "from_config should raise on missing entry point"

        # Simulate __post_init__'s DenyAllPolicy fallback.
        m.hm_protocol.policy_chain = PolicyChain(
            policies=[DenyAllPolicy(hm_protocol=m.hm_protocol)],
        )

        seen = []
        m.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)
        denied = _capture_denied(s)

        _send_utterance(s)

        assert _wait_for(lambda: len(denied) >= 1), (
            f"DenyAllPolicy fallback did not notify client: {denied}"
        )
        assert seen == [], (
            f"DenyAllPolicy fallback let a message through: {seen}"
        )
        assert denied[0].data["code"] == "policy_chain_unavailable"
    finally:
        b.stop_all()


def test_policy_exception_becomes_policy_error_under_fail_closed():
    """A policy raising in review() is converted to
    Verdict.deny('policy_error', ...) — the chain is always fail-closed.
    Client receives hive.policy.denied.
    """
    from hivemind_core.policy import PolicyChain
    from hivemind_plugin_manager import PolicyPlugin

    class _ExplodingPolicy(PolicyPlugin):
        def review(self, message, client):
            raise RuntimeError("kaboom")

    b, m = _build(allowed_types=["recognizer_loop:utterance"])
    try:
        b.start_all()
        s = b.get_satellite("S0")
        m.hm_protocol.policy_chain = PolicyChain(
            policies=[_ExplodingPolicy(hm_protocol=m.hm_protocol)],
        )

        seen = []
        m.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)
        denied = _capture_denied(s)

        _send_utterance(s)

        assert _wait_for(lambda: len(denied) >= 1), denied
        assert seen == [], seen
        assert denied[0].data["code"] == "policy_error"
    finally:
        b.stop_all()


def test_review_binary_deny_blocks_dispatch():
    """A policy that denies on review_binary blocks the binary handler
    from running and notifies the client.
    """
    from hivemind_bus_client.message import HiveMindBinaryPayloadType
    from hivemind_core.policy import PolicyChain
    from hivemind_plugin_manager import PolicyPlugin, Verdict

    class _DenyBinaryPolicy(PolicyPlugin):
        def review_binary(self, payload, client):
            return Verdict.deny("oversize",
                                "binary payloads disallowed in this test")

    b, m = _build(allowed_types=["recognizer_loop:utterance"])
    try:
        b.start_all()
        s = b.get_satellite("S0")
        m.hm_protocol.policy_chain = PolicyChain(
            policies=[_DenyBinaryPolicy(hm_protocol=m.hm_protocol)],
        )

        # Spy on the binary handler — denial must short-circuit it.
        called = []
        orig = m.hm_protocol.binary_data_protocol.handle_microphone_input
        m.hm_protocol.binary_data_protocol.handle_microphone_input = (
            lambda *a, **kw: called.append(a)
        )

        denied = _capture_denied(s)

        s.send(HiveMessage(
            HiveMessageType.BINARY,
            payload=b"\x00" * 32,
            bin_type=HiveMindBinaryPayloadType.RAW_AUDIO,
            metadata={"sample_rate": 16000, "sample_width": 2},
        ))

        try:
            assert _wait_for(lambda: len(denied) >= 1), denied
            assert called == [], (
                f"binary handler ran despite review_binary deny: {called}"
            )
            assert denied[0].data["code"] == "oversize"
            assert denied[0].data["denied_type"] == "binary"
        finally:
            m.hm_protocol.binary_data_protocol.handle_microphone_input = orig
    finally:
        b.stop_all()
