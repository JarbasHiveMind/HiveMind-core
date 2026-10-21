"""``ovos.utterance.handle`` (OVOS-PIPELINE-1 §9.1) through a real hub.

A satellite sends the spec utterance topic over the real wire. On the inject
path a cancelling transformer stops it, and on the QUERY path the utterance is
extracted, transformed and answered, exactly as for ``recognizer_loop:utterance``.
"""
from __future__ import annotations

import time

import pytest

pytest.importorskip("hivescope")

from hivemind_bus_client.message import HiveMessage, HiveMessageType  # noqa: E402
from hivescope.topology import TopologyBuilder  # noqa: E402
from ovos_bus_client.message import Message  # noqa: E402
from ovos_bus_client.session import Session  # noqa: E402

TOPICS = ["ovos.utterance.handle", "recognizer_loop:utterance"]


class _Transformer:
    """Rewrites every utterance and cancels those containing 'forbidden'."""
    plugins = ["fake"]

    def transform(self, utterances, context=None):
        context = dict(context or {})
        if any("forbidden" in u for u in utterances):
            context.update(canceled=True, cancel_reason="forbidden word",
                           cancel_by="fake")
        return [f"corrected:{u}" for u in utterances], context


def _wait_for(condition, timeout=3.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


def _build(topic):
    b = TopologyBuilder()
    m = b.add_master("M0")
    b.add_satellite("S0", upstream=m, allowed_types=[topic])
    return b, m


def _bus_inbox(satellite):
    got = []

    def _on(msg):
        if isinstance(getattr(msg, "payload", None), Message):
            got.append(msg.payload)

    satellite.shim.emitter.on(HiveMessageType.BUS, _on)
    return got


def _utterance(satellite, topic, text):
    sess = Session(session_id=satellite.shim.session_id, site_id="client-site")
    return Message(topic, {"utterances": [text], "lang": "en-US"},
                   {"session": sess.serialize()})


@pytest.mark.parametrize("topic", TOPICS)
def test_cancelling_transformer_stops_the_utterance(topic):
    b, m = _build(topic)
    try:
        b.start_all()
        s = b.get_satellite("S0")
        m.hm_protocol.utterance_transformers = _Transformer()
        reached = []
        m.agent_protocol.bus.on(topic, reached.append)
        inbox = _bus_inbox(s)

        s.send(HiveMessage(HiveMessageType.BUS,
                           payload=_utterance(s, topic, "this is forbidden")))

        assert _wait_for(lambda: any(
            p.msg_type == "ovos.utterance.handled" for p in inbox)), \
            [p.msg_type for p in inbox]
        assert [p.msg_type for p in inbox
                if p.msg_type.startswith("ovos.utterance.")] == [
            "ovos.utterance.cancelled", "ovos.utterance.handled"]
        assert reached == []
    finally:
        b.stop_all()


@pytest.mark.parametrize("topic", TOPICS)
def test_uncancelled_utterance_is_rewritten_and_keeps_its_topic(topic):
    b, m = _build(topic)
    try:
        b.start_all()
        s = b.get_satellite("S0")
        m.hm_protocol.utterance_transformers = _Transformer()
        reached = []
        m.agent_protocol.bus.on(topic, reached.append)

        s.send(HiveMessage(HiveMessageType.BUS,
                           payload=_utterance(s, topic, "hello")))

        assert _wait_for(lambda: reached)
        assert reached[0].msg_type == topic
        assert reached[0].data["utterances"] == ["corrected:hello"]
    finally:
        b.stop_all()


@pytest.mark.parametrize("topic", TOPICS)
def test_query_path_is_answered_through_the_transformers(topic):
    b, m = _build(topic)
    try:
        b.start_all()
        s = b.get_satellite("S0")
        m.hm_protocol.utterance_transformers = _Transformer()
        asked = []

        def _responder(msg):
            asked.append(msg.data["utterances"])
            qid = msg.context.get("query_id")
            bus = m.agent_protocol.bus
            bus.emit(Message("speak", {"utterance": "the weather is sunny"},
                             {"query_id": qid}))
            bus.emit(Message("ovos.utterance.handled", {}, {"query_id": qid}))

        # the agent protocol puts the query on the bus under its own topic
        for agent_topic in set(TOPICS):
            m.agent_protocol.bus.on(agent_topic, _responder)
        inner = HiveMessage(HiveMessageType.BUS, payload=_utterance(s, topic, "weather"))
        s.send(HiveMessage(HiveMessageType.QUERY, payload=inner,
                           metadata={"query_id": "q1", "originator_peer": s.peer}))

        recv = s.recorder.wait_for(HiveMessageType.QUERY.value,
                                   direction="in", timeout=3.0)
        assert recv is not None, "satellite never received a QUERY response"
        assert asked and asked[0] == ["corrected:weather"]
    finally:
        b.stop_all()
