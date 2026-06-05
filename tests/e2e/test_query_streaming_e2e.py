"""Deeper QUERY/CASCADE coverage the basic round-trip e2e don't exercise:
multi-chunk streaming, an agent that answers asynchronously (after the inject
returns — the real OVOS case the synchronous FakeBus path would miss), relay
escalation when the local agent can't answer, and CASCADE response collection.
"""
import threading
import time

import pytest

pytest.importorskip("hivescope")

from hivemind_bus_client.message import HiveMessage, HiveMessageType  # noqa: E402
from ovos_bus_client.message import Message  # noqa: E402
from hivescope.topology import TopologyBuilder  # noqa: E402


def _utt(text="weather"):
    return HiveMessage(HiveMessageType.BUS,
                       payload=Message("recognizer_loop:utterance", {"utterances": [text]}))


def _single():
    b = TopologyBuilder()
    m = b.add_master("M0")
    m.register_satellite("k", password="p", allowed_types=["recognizer_loop:utterance"])
    b.add_satellite("S0", upstream=m, allowed_types=["recognizer_loop:utterance"])
    return b


def _relay_chain():
    b = TopologyBuilder()
    m = b.add_master("M0")
    m.register_satellite("relay-key", password="relay-pw")
    _sat, master_side = b.add_relay("R0", upstream=m)
    master_side.register_satellite("sat-key", password="sat-pw",
                                   allowed_types=["recognizer_loop:utterance"])
    b.add_satellite("S0", upstream=master_side, allowed_types=["recognizer_loop:utterance"])
    return b


def _answer(master, sentences, delay=0.0):
    """Register an agent responder that speaks *sentences* (optionally after a
    threaded *delay*) tagged with the injected query_id, then signals handled."""
    def _responder(msg):
        qid = msg.context.get("query_id")
        bus = master.agent_protocol.bus

        def _emit():
            for s in sentences:
                bus.emit(Message("speak", {"utterance": s}, {"query_id": qid}))
            bus.emit(Message("ovos.utterance.handled", {}, {"query_id": qid}))
        if delay:
            threading.Thread(target=_emit, daemon=True).start()
        else:
            _emit()
    master.agent_protocol.bus.on("recognizer_loop:utterance", _responder)


def test_query_streams_multiple_chunks():
    b = _single(); b.start_all()
    try:
        _answer(b.get_master("M0"), ["first.", "second.", "third."])
        s = b.get_satellite("S0")
        s.send(HiveMessage(HiveMessageType.QUERY, payload=_utt(),
                           metadata={"query_id": "q1", "originator_peer": s.peer}))
        time.sleep(0.5)
        got = s.recorder.received(HiveMessageType.QUERY.value, direction="in")
        assert len(got) >= 3, f"expected >=3 streamed QUERY responses, got {len(got)}"
    finally:
        b.stop_all()


def test_query_async_agent_answer_is_collected():
    """The agent answers on another thread, 0.3s after the inject returns —
    the streaming wait must still capture it."""
    b = _single(); b.start_all()
    try:
        _answer(b.get_master("M0"), ["the async answer"], delay=0.3)
        s = b.get_satellite("S0")
        s.send(HiveMessage(HiveMessageType.QUERY, payload=_utt(),
                           metadata={"query_id": "q2", "originator_peer": s.peer}))
        recv = s.recorder.wait_for(HiveMessageType.QUERY.value, direction="in", timeout=4.0)
        assert recv is not None, "async agent answer never reached the satellite"
    finally:
        b.stop_all()


def test_query_escalates_up_the_relay_chain():
    """S0's QUERY can't be answered by the relay R0 (no agent responder there);
    it escalates to M0, which answers, and the response routes back to S0."""
    b = _relay_chain(); b.start_all()
    try:
        _answer(b.get_master("M0"), ["answered upstream"])  # only the top master answers
        s = b.get_satellite("S0")
        s.send(HiveMessage(HiveMessageType.QUERY, payload=_utt(),
                           metadata={"query_id": "q3", "originator_peer": s.peer}))
        recv = s.recorder.wait_for(HiveMessageType.QUERY.value, direction="in", timeout=6.0)
        assert recv is not None, "escalated QUERY answer never routed back to S0"
    finally:
        b.stop_all()


def test_cascade_round_trip_single_node():
    b = _single(); b.start_all()
    try:
        _answer(b.get_master("M0"), ["cascade answer"])
        s = b.get_satellite("S0")
        s.send(HiveMessage(HiveMessageType.CASCADE, payload=_utt(),
                           metadata={"query_id": "c1", "originator_peer": s.peer}))
        recv = s.recorder.wait_for(HiveMessageType.CASCADE.value, direction="in", timeout=4.0)
        assert recv is not None, "satellite never received a CASCADE response"
    finally:
        b.stop_all()


def _two_relay_chain():
    """M0 (answers) <- R1 <- R2 <- S0 (originator). A QUERY from S0 traverses
    R2 then R1 — neither answers — and only M0, the third node up the chain,
    answers; the response then routes back down through R1 and R2 to S0."""
    b = TopologyBuilder()
    m = b.add_master("M0")
    m.register_satellite("r1-key", password="p")
    _s1, r1_master = b.add_relay("R1", upstream=m)
    r1_master.register_satellite("r2-key", password="p")
    _s2, r2_master = b.add_relay("R2", upstream=r1_master)
    r2_master.register_satellite("sat-key", password="p",
                                 allowed_types=["recognizer_loop:utterance"])
    b.add_satellite("S0", upstream=r2_master,
                    allowed_types=["recognizer_loop:utterance"])
    return b


def test_query_traverses_two_relays_only_third_answers():
    b = _two_relay_chain(); b.start_all()
    try:
        # ONLY the top master answers; R2 and R1 have no agent answer -> escalate
        _answer(b.get_master("M0"), ["answered at the top after two hops"])
        s = b.get_satellite("S0")
        s.send(HiveMessage(HiveMessageType.QUERY, payload=_utt(),
                           metadata={"query_id": "q-deep", "originator_peer": s.peer}))
        recv = s.recorder.wait_for(HiveMessageType.QUERY.value,
                                   direction="in", timeout=12.0)
        assert recv is not None, \
            "QUERY answered at M0 never routed back through R1+R2 to S0"
    finally:
        b.stop_all()
