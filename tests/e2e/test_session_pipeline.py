"""End-to-end coverage for the session-pipeline preservation fix.

Mirrors the unit tests in ``tests/test_session_pipeline.py`` but exercises
the behaviour through the real master/satellite protocol stack via
hivescope, so regressions in any layer (network, slave protocol, listener
protocol) get caught.
"""

import time
from unittest.mock import MagicMock

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from hivescope.scenarios import admin_satellite
from hivescope.topology import TopologyBuilder


def _non_admin_satellite():
    """Non-admin counterpart to ``admin_satellite()``.

    Needed for tests that probe the ``session_id == "default"`` rejection,
    which only fires for non-admin peers. ``allowed_types`` is set
    explicitly because ``recognizer_loop:utterance`` is not in the default
    allowlist for non-admin satellites.
    """
    b = TopologyBuilder()
    m = b.add_master("M0")
    m.register_satellite(
        "test-key",
        password="test-password",
        is_admin=False,
        allowed_types=["recognizer_loop:utterance"],
    )
    b.add_satellite("S0", upstream=m)
    return b


def _wait_for(condition, timeout: float = 2.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


def _send_bus(satellite, session_dict):
    """Send ``recognizer_loop:utterance`` with an explicit session context.

    ``SatelliteNode.send`` only injects a default session when ``"session"``
    is missing entirely, so passing one here is enough to control what the
    master sees on the wire.
    """
    msg = Message(
        "recognizer_loop:utterance",
        {"utterances": ["hello"]},
        {"session": session_dict},
    )
    satellite.send(HiveMessage(HiveMessageType.BUS, payload=msg))


def _emitted_session(master):
    assert _wait_for(lambda: len(master.agent_protocol.injected) >= 1), (
        f"no message was injected on master bus: {master.agent_protocol.injected}"
    )
    return master.agent_protocol.injected[-1].context.get("session", {})


def test_no_pipeline_in_payload_is_not_invented_from_core_config():
    b = admin_satellite()
    try:
        b.start_all()
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        sess = Session(session_id=s.shim.session_id, site_id="client-site")
        ctx = sess.serialize()
        ctx.pop("pipeline", None)
        _send_bus(s, ctx)

        emitted = _emitted_session(m)
        assert "pipeline" not in emitted or emitted.get("pipeline") in (None, []), (
            f"core invented a pipeline for a client that did not send one: {emitted}"
        )
    finally:
        b.stop_all()


def test_explicit_pipeline_list_is_preserved():
    b = admin_satellite()
    try:
        b.start_all()
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        sess = Session(session_id=s.shim.session_id, site_id="client-site")
        ctx = sess.serialize()
        ctx["pipeline"] = ["client-sent-pipeline"]
        _send_bus(s, ctx)

        emitted = _emitted_session(m)
        assert emitted.get("pipeline") == ["client-sent-pipeline"], emitted
    finally:
        b.stop_all()


def test_explicit_none_pipeline_is_preserved():
    b = admin_satellite()
    try:
        b.start_all()
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        sess = Session(session_id=s.shim.session_id, site_id="client-site")
        ctx = sess.serialize()
        ctx["pipeline"] = None
        _send_bus(s, ctx)

        emitted = _emitted_session(m)
        assert emitted.get("pipeline") is None, emitted
    finally:
        b.stop_all()


def test_agent_bus_callback_fires_exactly_once_per_bus_message():
    """Regression guard for the duplicate-callback bug.

    ``handle_inject_agent_msg`` already invokes ``agent_bus_callback``;
    before the fix, ``handle_bus_message`` invoked it a second time.
    """
    b = admin_satellite()
    try:
        b.start_all()
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        callback = MagicMock()
        m.hm_protocol.agent_bus_callback = callback

        sess = Session(session_id=s.shim.session_id, site_id="client-site")
        _send_bus(s, sess.serialize())

        assert _wait_for(lambda: callback.call_count >= 1)
        # Give any duplicate dispatch a chance to land before asserting count==1.
        time.sleep(0.05)
        assert callback.call_count == 1, (
            f"agent_bus_callback fired {callback.call_count} times, expected 1"
        )
    finally:
        b.stop_all()


def test_non_admin_default_session_id_is_denied_by_policy():
    """Non-admin client injecting session_id='default' is denied by
    OVOSAgentPolicy (previously caused a connection disconnect; the
    check moved to the policy chain in HiveMind-core#85 / #89 so the
    response is now a clean ``hive.policy.denied`` with
    ``code='session_id_default_forbidden'``)."""
    b = _non_admin_satellite()
    try:
        b.start_all()
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        _send_bus(s, {"session_id": "default", "site_id": "client-site"})

        time.sleep(0.5)
        # The message must not have reached the agent bus.
        assert not any(
            msg.msg_type == "recognizer_loop:utterance"
            for msg in m.agent_protocol.injected
        ), m.agent_protocol.injected
    finally:
        b.stop_all()


def test_non_admin_payload_without_session_is_denied_by_policy():
    """Missing session in payload defaults to ``default`` and is denied
    by OVOSAgentPolicy (was a disconnect, now a policy deny)."""
    b = _non_admin_satellite()
    try:
        b.start_all()
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        # Build the BUS message with NO session in context — Session.from_message
        # will fall back to the reserved 'default' id; OVOSAgentPolicy denies.
        msg = Message(
            "recognizer_loop:utterance", {"utterances": ["hello"]}, {}
        )
        s.send(HiveMessage(HiveMessageType.BUS, payload=msg))

        time.sleep(0.5)
        assert not any(
            mm.msg_type == "recognizer_loop:utterance"
            for mm in m.agent_protocol.injected
        ), m.agent_protocol.injected
    finally:
        b.stop_all()


def test_admin_default_session_id_is_allowed():
    """Counterpart: admin clients may use ``default`` and the message lands."""
    b = admin_satellite()
    try:
        b.start_all()
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        peer = next(iter(m.hm_protocol.clients))
        client = m.hm_protocol.clients[peer]
        client.disconnect = MagicMock()

        _send_bus(s, {"session_id": "default", "site_id": "client-site"})

        assert _wait_for(lambda: len(m.agent_protocol.injected) >= 1)
        assert not client.disconnect.called, (
            "admin client using session_id='default' was wrongly disconnected"
        )
    finally:
        b.stop_all()


def test_stale_master_side_pipeline_is_not_reattached():
    """End-to-end exercise for the ``_update_blacklist`` fix.

    If the master-side connection has a leftover pipeline from a prior
    message, sending a new BUS payload without pipeline must not cause it
    to be reattached on its way to the agent bus.
    """
    b = admin_satellite()
    try:
        b.start_all()
        m = b.get_master("M0")
        s = b.get_satellite("S0")

        peer = next(iter(m.hm_protocol.clients))
        m.hm_protocol.clients[peer].sess.pipeline = ["stale-pipeline"]

        sess = Session(session_id=s.shim.session_id, site_id="client-site")
        ctx = sess.serialize()
        ctx.pop("pipeline", None)
        _send_bus(s, ctx)

        emitted = _emitted_session(m)
        assert emitted.get("pipeline") in (None, [], ), (
            f"stale master-side pipeline leaked into agent bus: {emitted}"
        )
        assert emitted.get("pipeline") != ["stale-pipeline"]
    finally:
        b.stop_all()
