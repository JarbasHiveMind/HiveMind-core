"""A QUERY or CASCADE that a node's own policy chain denied is never relayed.

HIVEMIND-MSG-1 §5.1: "A rejected or unauthenticated message MUST NOT be
relayed as a side effect of being refused ... a refusal is handled — the frame
is consumed and dropped."  HIVEMIND-POLICY-1 §6: the client receives
``hive.policy.denied``.  A decline is different (HIVEMIND-AGENT-1 §5): the node
had no answer, so it escalates.

Topology: M0 <- R0 <- {restricted, open, peer}.  M0 and R0 each run an agent
whose utterance handlers are recorded, so "answered upstream" and "ran on a
peer" are observed on the agent bus and not inferred from silence.
"""
import time

import pytest

pytest.importorskip("hivescope")

from hivemind_bus_client.message import HiveMessage, HiveMessageType  # noqa: E402
from ovos_bus_client.message import Message  # noqa: E402
from ovos_bus_client.session import Session  # noqa: E402
from hivescope.topology import TopologyBuilder  # noqa: E402

from hivemind_core.protocol import UTTERANCE_TOPICS  # noqa: E402

UTTERANCE = "recognizer_loop:utterance"
TOPICS = sorted(UTTERANCE_TOPICS)


def _topology():
    b = TopologyBuilder()
    m = b.add_master("M0")
    r0 = b.add_relay("R0", upstream=m, allowed_types=[UTTERANCE]).listener
    b.add_satellite("restricted", upstream=r0, allowed_types=["speak"])
    b.add_satellite("open", upstream=r0, allowed_types=[UTTERANCE])
    b.add_satellite("peer", upstream=r0, allowed_types=[UTTERANCE])
    return b


def _record_and_answer(node, ran, sentence):
    """Record each utterance the node's agent receives and answer it."""
    def _responder(msg):
        ran.append(msg.data["utterances"][0])
        qid = msg.context.get("query_id")
        bus = node.agent_protocol.bus
        bus.emit(Message("speak", {"utterance": sentence}, {"query_id": qid}))
        bus.emit(Message("ovos.utterance.handled", {}, {"query_id": qid}))
    for topic in TOPICS:
        node.agent_protocol.bus.on(topic, _responder)


def _capture_denied(satellite):
    captured = []

    def _on(msg):
        payload = getattr(msg, "payload", None)
        if isinstance(payload, Message) and payload.msg_type == "hive.policy.denied":
            captured.append(payload)

    satellite.shim.emitter.on(HiveMessageType.BUS, _on)
    return captured


def _query(satellite, msg_type, query_id, text, topic=UTTERANCE):
    session = Session(session_id=satellite.shim.session_id, site_id="client-site")
    inner = HiveMessage(HiveMessageType.BUS, payload=Message(
        topic, {"utterances": [text]}, {"session": session.serialize()}))
    satellite.send(HiveMessage(msg_type, payload=inner, metadata={
        "query_id": query_id, "originator_peer": satellite.peer}))


def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _answers(satellite, msg_type):
    return satellite.recorder.received(msg_type.value, direction="in")


@pytest.mark.parametrize("topic", TOPICS)
def test_denied_query_is_not_answered_upstream(topic):
    b = _topology()
    b.start_all()
    try:
        upstream_ran, relay_ran = [], []
        _record_and_answer(b.get_master("M0"), upstream_ran, "upstream answer")
        _record_and_answer(b.get_relay("R0").listener, relay_ran, "relay answer")
        restricted = b.get_satellite("restricted")
        denied = _capture_denied(restricted)

        _query(restricted, HiveMessageType.QUERY, "q-denied", "forbidden", topic)

        assert _wait(lambda: denied), "the client never received hive.policy.denied"
        assert denied[0].data["denied_type"] == topic
        assert denied[0].data["code"] == "acl_disallowed_type"
        time.sleep(1.0)
        assert upstream_ran == [], "the upstream node answered a denied QUERY"
        assert relay_ran == [], "the relay answered a QUERY its own chain denied"
        assert _answers(restricted, HiveMessageType.QUERY) == [], \
            "the denied client received an answer after hive.policy.denied"
    finally:
        b.stop_all()


@pytest.mark.parametrize("topic", TOPICS)
def test_denied_cascade_runs_on_no_peer(topic):
    b = _topology()
    b.start_all()
    try:
        upstream_ran, relay_ran = [], []
        _record_and_answer(b.get_master("M0"), upstream_ran, "upstream answer")
        _record_and_answer(b.get_relay("R0").listener, relay_ran, "relay answer")
        restricted = b.get_satellite("restricted")
        peer = b.get_satellite("peer")
        denied = _capture_denied(restricted)

        _query(restricted, HiveMessageType.CASCADE, "c-denied", "forbidden", topic)

        assert _wait(lambda: denied), "the client never received hive.policy.denied"
        time.sleep(1.0)
        assert upstream_ran == [], "a denied CASCADE ran on the upstream node"
        assert relay_ran == [], "a denied CASCADE ran on the relay"
        assert _answers(peer, HiveMessageType.CASCADE) == [], \
            "a denied CASCADE was fanned out to a peer client"
        assert _answers(restricted, HiveMessageType.CASCADE) == []
    finally:
        b.stop_all()


def test_declined_query_still_escalates_upstream():
    b = _topology()
    b.start_all()
    try:
        upstream_ran = []
        _record_and_answer(b.get_master("M0"), upstream_ran, "upstream answer")
        open_client = b.get_satellite("open")

        # R0's agent has no responder: it declines, and the QUERY escalates.
        _query(open_client, HiveMessageType.QUERY, "q-open", "weather")

        assert _wait(lambda: _answers(open_client, HiveMessageType.QUERY),
                     timeout=20.0), "the declined QUERY never escalated to M0"
        assert upstream_ran == ["weather"]
        spoken = _answers(open_client, HiveMessageType.QUERY)[0].payload
        assert spoken["payload"]["data"]["utterance"] == "upstream answer"
    finally:
        b.stop_all()
