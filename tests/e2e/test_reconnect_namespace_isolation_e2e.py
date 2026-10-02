"""End-to-end coverage for T-7192's live-stage gap: a bus reply that is
delayed across a clean disconnect/reconnect and still carries the OLD
connection's Layer-1 session namespace.

Mirrors ``tests/test_session_unnat_outbound.py`` (unit-level, a bare
``HiveMindClientConnection``) but drives the scenario through two real
connections wired by hivescope, so the reverse-routing path in
``TestAgentProtocol.handle_internal_mycroft`` is exercised too, not just
``HiveMindClientConnection.send()`` in isolation.

HIVEMIND-AGENT-1 §3.3 ("A response whose peer is gone"):

    The server MUST NOT select a different peer to receive the response by
    any identity other than the ``destination`` -- in particular not by a
    shared session namespace, a shared credential, or a shared site. [...]
    The server MUST log the undelivered response at WARNING, naming the
    ``destination`` it could not resolve, and the session when the response
    carries one. This is a diagnostic obligation on the server and not a
    wire conformance point, because no peer can observe it.

So the only observable the drop leaves is the server's own log record. A
cell that asserted on a wire field would be asserting on something this
clause says does not exist.

What makes the peer key recycle, and what does not
---------------------------------------------------
``HiveMindClientConnection.peer`` is ``f"{name}::{session_id}{suffix}"``
(HiveMind-core's ``protocol.py``) -- it carries the connection's declared
NAME and declared SESSION_ID, never its access key. The unit-level cells
this file mirrors construct their connections the same way: two bare
``HiveMindClientConnection`` objects given the same namespace, no DB row or
credential in sight. So the two live connections below are built as two
independent devices (independent identity, independent access key --
avoiding the server's TOFU Noise-key pin and PSK cache, which are keyed to
the DB row and are a different, unrelated conformance surface) that happen
to declare the same name and the same session_id. That is sufficient to
recycle the peer key, which is the only thing ``_unnat_outbound_session``
reads to decide whether a connection it is dropping for is a stranger.

A single ``SatelliteNode`` cannot be reconnected to model this: its
``HiveMindSlaveProtocol`` latches ``_noise_established`` and
``InProcessHiveShim.handshake_event`` for the object's lifetime, so a
second ``connect()`` call skips the Noise handshake and the slave never
re-sends its own HELLO -- the master-side connection would be stuck on the
placeholder session ``connect_satellite`` assigns it, not the declared
session_id a real second connection presents. A second, independently
created ``SatelliteNode`` runs its own handshake and HELLO for real.
"""
import logging

from ovos_bus_client.message import Message
from hivemind_bus_client.message import HiveMessageType

from hivescope.node import MasterNode, SatelliteNode


def _reconnect_same_peer(master: MasterNode, old: SatelliteNode) -> SatelliteNode:
    """Disconnect ``old`` cleanly and connect a second, independent satellite
    that declares the same name and the same session_id, recycling the peer
    key the first connection held.
    """
    peer = old.peer  # SatelliteNode.peer reads _connection, which disconnect() clears
    old_session_id = old.shim.session_id
    old.disconnect()
    assert peer not in master.hm_protocol.clients, (
        "a clean disconnect must pop the old connection before the peer "
        "key can be recycled"
    )

    new = SatelliteNode.create(old.name)
    # InProcessHiveShim.session_id has no public setter: the shim mints its
    # own uuid4 session_id at construction, and a device reconnecting with
    # the session_id it already declared is exactly the case under test.
    new.shim._session_id = old_session_id
    new.connect(master, is_admin=False)
    assert new.peer == peer, (
        f"test setup did not recycle the peer key: old={peer!r} "
        f"new={new.peer!r}"
    )
    return new


def test_delayed_reply_across_reconnect_reaches_nobody_and_is_logged(caplog):
    """A reply addressed to a Layer-1 session whose connection is gone is
    dropped, not delivered through the peer key a reconnect recycled, and
    the drop is logged at WARNING naming the session and the destination.
    """
    m = MasterNode.create("M0")
    s_old = SatelliteNode.create("S0")
    s_new = None
    try:
        s_old.connect(m, is_admin=False)
        peer = s_old.peer
        old_conn = m.hm_protocol.clients[peer]
        old_layer1 = old_conn.layer1_session_id  # f"{old_namespace}:{declared}"

        s_new = _reconnect_same_peer(m, s_old)
        new_conn = m.hm_protocol.clients[peer]
        assert new_conn is not old_conn
        assert new_conn.session_namespace != old_conn.session_namespace, (
            "the reconnected connection must mint its own Layer-1 "
            "namespace; a shared one is the T-6696 defect this guard exists "
            "to close"
        )

        caplog.set_level(logging.WARNING, logger="hivemind_core.protocol")
        m.emit_on_bus(Message(
            "speak",
            data={"utterance": "a stale reply for the device that left"},
            context={"destination": peer, "session": {"session_id": old_layer1}},
        ))

        recv = s_new.recorder.wait_for(HiveMessageType.BUS.value, direction="in",
                                       timeout=1.0)
        assert recv is None, (
            f"the reconnected peer must receive NOTHING for a reply "
            f"addressed to the recycled peer key under the old namespace, "
            f"got: {recv}"
        )

        warnings = [r.getMessage() for r in caplog.records
                   if r.name == "hivemind_core.protocol"
                   and r.levelno == logging.WARNING]
        assert any(old_layer1 in msg and peer in msg for msg in warnings), (
            f"expected a WARNING naming the unresolved session {old_layer1!r} "
            f"and destination {peer!r}; got: {warnings}"
        )
    finally:
        s_old.disconnect()
        s_old.cleanup()
        if s_new is not None:
            s_new.disconnect()
            s_new.cleanup()
        m.cleanup()


def test_reply_carrying_new_namespace_still_arrives_after_reconnect():
    """Control: a reply correctly addressed under the RECONNECTED
    connection's own Layer-1 session still arrives, with the client's own
    declared session_id restored (HIVEMIND-BRIDGE-1 §4 outbound MUST).

    Without this control, a cell that dropped every reply after any
    reconnect -- not just one carrying a foreign namespace -- would also
    pass the test above.
    """
    m = MasterNode.create("M0")
    s_old = SatelliteNode.create("S0")
    s_new = None
    try:
        s_old.connect(m, is_admin=False)
        peer = s_old.peer

        s_new = _reconnect_same_peer(m, s_old)
        new_conn = m.hm_protocol.clients[peer]
        new_layer1 = new_conn.layer1_session_id
        declared = s_new.shim.session_id

        m.emit_on_bus(Message(
            "speak",
            data={"utterance": "a fresh reply for the device that is here"},
            context={"destination": peer, "session": {"session_id": new_layer1}},
        ))

        recv = s_new.recorder.wait_for(HiveMessageType.BUS.value, direction="in",
                                       timeout=2.0)
        assert recv is not None, "the reconnected peer must receive its own reply"

        payload = recv.payload if isinstance(recv.payload, dict) else {}
        actual_sid = (payload.get("context") or {}).get("session", {}).get("session_id")
        assert actual_sid == declared, (
            f"BRIDGE-1 §4 outbound MUST: the client must see the session_id "
            f"it declared, not the internal namespace; expected {declared!r}, "
            f"got {actual_sid!r}"
        )
    finally:
        s_old.disconnect()
        s_old.cleanup()
        if s_new is not None:
            s_new.disconnect()
            s_new.cleanup()
        m.cleanup()
