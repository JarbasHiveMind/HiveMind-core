"""A node's own answer to a relayed CASCADE reaches the asker through the relay.

HIVEMIND-MSG-1 §5.2: an answer is delivered to the return path the node
recorded, and never back to the peer it arrived from.  An answer that M0
produces itself arrived from no peer, so the relay that forwarded the CASCADE
is its return path.  Topology: asker -> R0 -> M0, only M0 answers.
"""
import time

import pytest

pytest.importorskip("hivescope")

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivescope.topology import TopologyBuilder
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

UTTERANCE = "recognizer_loop:utterance"


def _wait(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _answered_cascade(metadata):
    """Send a CASCADE through R0 to M0, which answers it, and return the texts
    the asker received."""
    b = TopologyBuilder()
    m = b.add_master("M0")
    r0 = b.add_relay("R0", upstream=m, allowed_types=[UTTERANCE]).listener
    b.add_satellite("asker", upstream=r0, allowed_types=[UTTERANCE])
    b.start_all()
    try:
        master = b.get_master("M0")

        def _responder(msg):
            qid = msg.context.get("query_id")
            bus = master.agent_protocol.bus
            bus.emit(Message("speak", {"utterance": "upstream answer"}, {"query_id": qid}))
            bus.emit(Message("ovos.utterance.handled", {}, {"query_id": qid}))
        master.agent_protocol.bus.on(UTTERANCE, _responder)

        asker = b.get_satellite("asker")
        session = Session(session_id=asker.shim.session_id, site_id="client-site")
        inner = HiveMessage(HiveMessageType.BUS, payload=Message(
            UTTERANCE, {"utterances": ["weather"]}, {"session": session.serialize()}))
        asker.send(HiveMessage(HiveMessageType.CASCADE, payload=inner,
                               metadata=metadata(asker)))

        def spoken():
            return [r.payload["payload"]["data"]["utterance"]
                    for r in asker.recorder.received(
                        HiveMessageType.CASCADE.value, direction="in")
                    if "utterance" in r.payload["payload"]["data"]]

        _wait(spoken)
        time.sleep(0.5)
        return spoken()
    finally:
        b.stop_all()


def test_cascade_answered_by_the_upstream_node_reaches_the_asker():
    spoken = _answered_cascade(lambda asker: {
        "query_id": "cascade-1", "originator_peer": asker.peer})
    assert spoken == ["upstream answer"], "the CASCADE answer never reached the asker"


# hivemind-bus-client sends a CASCADE with no query_id; the relay mints one.
def test_cascade_without_query_id_is_answered_through_a_relay():
    spoken = _answered_cascade(lambda asker: None)
    assert spoken == ["upstream answer"]
