"""CASCADE gathering keys responses by query identifier and responder.

HIVEMIND-AGENT-1 §4.3: "A gatherer MUST key collected responses by query
identifier and responder, and MUST NOT let the state for never-completed
CASCADE gatherings accumulate without limit."

The collector map is keyed by query id. Inside a collector, each responder
gets one entry that its chunks accumulate into — so a caller can tell which
node said what, and two nodes answering the same cascade never mix.
"""
from ovos_bus_client.message import Message
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import CascadeCollector


def _chunk(responder: str, utterance: str, site_id: str = "") -> HiveMessage:
    return HiveMessage(
        HiveMessageType.CASCADE,
        payload=HiveMessage(HiveMessageType.BUS,
                            payload=Message("speak", {"utterance": utterance})),
        metadata={"query_id": "q1", "is_response": True,
                  "originator_peer": "asker::1",
                  "responder_peer": responder,
                  "responder_site_id": site_id})


def test_two_responders_get_one_entry_each():
    collector = CascadeCollector(query_id="q1", originator_peer="asker::1")

    collector.add_response(_chunk("node-A", "answer A"))
    collector.add_response(_chunk("node-B", "answer B"))

    by_peer = {r.responder_peer: r for r in collector.responses}
    assert set(by_peer) == {"node-A", "node-B"}
    assert [m.data["utterance"] for m in by_peer["node-A"].messages] == ["answer A"]
    assert [m.data["utterance"] for m in by_peer["node-B"].messages] == ["answer B"]


def test_chunks_from_one_responder_accumulate_in_its_entry():
    """A streamed answer is many chunks but one responder's answer."""
    collector = CascadeCollector(query_id="q1", originator_peer="asker::1")

    collector.add_response(_chunk("node-A", "first"))
    collector.add_response(_chunk("node-A", "second"))
    collector.add_response(_chunk("node-A", "third"))

    assert len(collector.responses) == 1, (
        "one responder's chunk stream was split into several responses")
    assert [m.data["utterance"] for m in collector.responses[0].messages] == [
        "first", "second", "third"]


def test_the_same_response_object_is_returned_for_a_repeat_responder():
    collector = CascadeCollector(query_id="q1", originator_peer="asker::1")

    first = collector.add_response(_chunk("node-A", "first"))
    second = collector.add_response(_chunk("node-A", "second"))

    assert first is second


def test_responder_order_of_first_arrival_is_kept():
    collector = CascadeCollector(query_id="q1", originator_peer="asker::1")

    collector.add_response(_chunk("node-B", "b1"))
    collector.add_response(_chunk("node-A", "a1"))
    collector.add_response(_chunk("node-B", "b2"))

    assert [r.responder_peer for r in collector.responses] == ["node-B", "node-A"]


def test_site_id_and_metadata_are_kept():
    collector = CascadeCollector(query_id="q1", originator_peer="asker::1")

    collector.add_response(_chunk("node-A", "a1", site_id="site-a"))

    resp = collector.responses[0]
    assert resp.responder_site_id == "site-a"
    assert resp.metadata["query_id"] == "q1"


def test_an_unnamed_responder_is_still_collected():
    collector = CascadeCollector(query_id="q1", originator_peer="asker::1")
    msg = _chunk("node-A", "a1")
    msg.metadata.pop("responder_peer")

    collector.add_response(msg)

    assert [r.responder_peer for r in collector.responses] == ["unknown"]
