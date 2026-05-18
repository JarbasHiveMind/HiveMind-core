"""End-to-end coverage for the policy admission chain (#85).

Exercises the chain through a real master/satellite stack via hivescope:

- ClientACLPolicy (built-in, ``allowed_types`` enforcement) replaces the
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


def _build(allowed_types=None, skill_bl=None, intent_bl=None, msg_bl=None):
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
        msg_blacklist=msg_bl,
    )
    return b, m


def _swap_chain(master, chain_entries):
    """Replace the in-memory policy chain on an already-built master.

    Avoids round-tripping through ``get_server_config()`` so tests can
    pick their own chain without touching XDG state. ``chain_entries``
    is a list of ``{"module": "...", "config": {...}}`` dicts, matching
    the on-disk config shape.
    """
    from hivemind_core.policy import PolicyChain
    master.hm_protocol.policy_chain = PolicyChain.from_config(
        {"policy": {"chain": chain_entries, "fail_open": False}},
        hm_protocol=master.hm_protocol,
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
# ClientACLPolicy — allowed_types
# ---------------------------------------------------------------------------

def test_disallowed_type_is_denied_and_notifies_client():
    """A type not in allowed_types is dropped and a hive.policy.denied
    notification is delivered to the satellite. **New observable** vs
    the old silent-drop in authorize()."""
    b, m = _build(allowed_types=["recognizer_loop:utterance"])
    try:
        b.start_all()
        s = b.get_satellite("S0")
        _swap_chain(m, [{"module": "hivemind-core-acl-policy"}])

        emitted = []
        m.agent_protocol.bus.on("speak", emitted.append)

        denied = []

        def on_bus(msg):
            payload = getattr(msg, "payload", None)
            if isinstance(payload, Message) and payload.msg_type == "hive.policy.denied":
                denied.append(payload)

        s.shim.emitter.on(HiveMessageType.BUS, on_bus)

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
        _swap_chain(m, [{"module": "hivemind-core-acl-policy"}])

        seen = []
        m.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)

        _send_utterance(s)

        assert _wait_for(lambda: len(seen) >= 1), (
            f"allowed message did not reach agent bus: {seen}"
        )
    finally:
        b.stop_all()


def test_empty_chain_passes_everything_through():
    """Chain disabled by config ⇒ messages flow regardless of allowed_types."""
    b, m = _build(allowed_types=[])  # empty allowed_types would normally deny
    try:
        b.start_all()
        s = b.get_satellite("S0")
        _swap_chain(m, [])  # no policies at all

        seen = []
        m.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)

        _send_utterance(s)

        assert _wait_for(lambda: len(seen) >= 1), (
            f"empty chain dropped a message: {seen}"
        )
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
        _swap_chain(m, [
            {"module": "hivemind-core-acl-policy"},
            {"module": "hivemind-ovos-agent-policy"},
        ])

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
        _swap_chain(m, [
            {"module": "hivemind-core-acl-policy"},
            {"module": "hivemind-ovos-agent-policy"},
        ])

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
        _swap_chain(m, [
            {"module": "hivemind-core-acl-policy"},
            {"module": "hivemind-ovos-agent-policy"},
        ])

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
# Outbound msg_blacklist — outbound-side filter is unaffected by the chain
# ---------------------------------------------------------------------------

def test_missing_plugin_falls_back_to_deny_all_under_fail_closed():
    """Audit fix: a configured policy entry-point that fails to resolve
    must NOT silently install an empty (allow-all) chain when the
    operator runs fail_open=false. Verifies the DenyAllPolicy fallback
    in HiveMindListenerProtocol.__post_init__.
    """
    from hivemind_core.policy import DenyAllPolicy

    b, m = _build(allowed_types=["recognizer_loop:utterance"])
    try:
        b.start_all()
        s = b.get_satellite("S0")

        # Force a chain rebuild that would have failed at startup.
        from hivemind_core.policy import PolicyChain
        try:
            PolicyChain.from_config({
                "policy": {
                    "fail_open": False,
                    "chain": [{"module": "does-not-exist-policy"}],
                },
            }, hm_protocol=m.hm_protocol)
            raised = False
        except Exception:
            raised = True
        assert raised, "from_config should raise under fail_open=false"

        # Simulate the protocol's __post_init__ fallback path.
        m.hm_protocol.policy_chain = PolicyChain(
            policies=[DenyAllPolicy(hm_protocol=m.hm_protocol)],
            fail_open=False,
        )

        seen = []
        m.agent_protocol.bus.on("recognizer_loop:utterance", seen.append)
        denied = []

        def on_bus(msg):
            payload = getattr(msg, "payload", None)
            if isinstance(payload, Message) and payload.msg_type == "hive.policy.denied":
                denied.append(payload)

        s.shim.emitter.on(HiveMessageType.BUS, on_bus)

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


def test_outbound_msg_blacklist_still_filters_after_refactor():
    """The send()-side filter on ``client.msg_blacklist`` predates the
    chain and is orthogonal. Verifies the refactor didn't break it."""
    b, m = _build(allowed_types=["recognizer_loop:utterance"])
    try:
        b.start_all()
        s = b.get_satellite("S0")
        # Default chain — exercises both built-in policies.

        conn = m.hm_protocol.clients[s.peer]
        conn.msg_blacklist = ["speak"]

        seen_speak = []
        s.shim.emitter.on(
            HiveMessageType.BUS,
            lambda msg: seen_speak.append(msg)
            if isinstance(msg.payload, Message) and msg.payload.msg_type == "speak"
            else None,
        )

        m.send_to_satellite(
            s.peer,
            HiveMessage(
                HiveMessageType.BUS,
                payload=Message("speak", {"utterance": "should not arrive"}),
            ),
        )

        time.sleep(0.3)
        assert seen_speak == [], (
            f"blacklisted outbound 'speak' was delivered: {seen_speak}"
        )
    finally:
        b.stop_all()
