"""A QUERY or CASCADE that arrives without ``query_id`` is answered end to end.

HIVEMIND-MSG-1 §5.2: the node that first admits a request mints ``query_id``
when it carries none, and carries ``query_id`` and ``originator_peer``
unchanged on every message it relays.  The relay R0 escalates the request to
M0; M0 must see the id R0 minted, or its answer matches no request at R0.
"""
import time

import pytest

pytest.importorskip("hivescope")

from hivemind_bus_client.message import HiveMessage, HiveMessageType  # noqa: E402
from ovos_bus_client.message import Message  # noqa: E402
from ovos_bus_client.session import Session  # noqa: E402
from hivescope.topology import TopologyBuilder  # noqa: E402

UTTERANCE = "recognizer_loop:utterance"


def _wait(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _answer_upstream(node):
    """Answer every utterance the node's agent receives."""
    def _responder(msg):
        qid = msg.context.get("query_id")
        bus = node.agent_protocol.bus
        bus.emit(Message("speak", {"utterance": "upstream answer"}, {"query_id": qid}))
        bus.emit(Message("ovos.utterance.handled", {}, {"query_id": qid}))
    node.agent_protocol.bus.on(UTTERANCE, _responder)


def _send_without_metadata(satellite, msg_type, metadata=None):
    session = Session(session_id=satellite.shim.session_id, site_id="client-site")
    inner = HiveMessage(HiveMessageType.BUS, payload=Message(
        UTTERANCE, {"utterances": ["weather"]}, {"session": session.serialize()}))
    satellite.send(HiveMessage(msg_type, payload=inner, metadata=metadata))


def _topology():
    b = TopologyBuilder()
    m = b.add_master("M0")
    r0 = b.add_relay("R0", upstream=m, allowed_types=[UTTERANCE]).listener
    b.add_satellite("asker", upstream=r0, allowed_types=[UTTERANCE])
    return b, r0


@pytest.mark.parametrize("msg_type", [HiveMessageType.QUERY, HiveMessageType.CASCADE])
def test_upstream_binds_the_id_the_relay_minted(msg_type):
    b, r0 = _topology()
    b.start_all()
    try:
        master = b.get_master("M0").hm_protocol
        asker = b.get_satellite("asker")
        _send_without_metadata(asker, msg_type)

        assert _wait(lambda: master._outstanding_queries, timeout=30.0), \
            "the upstream node never received the request"
        (upstream_id, _), = master._outstanding_queries.items()
        (relay_id, (relay_peer, _)), = r0.hm_protocol._outstanding_queries.items()
        assert relay_peer == asker.peer
        assert upstream_id == relay_id, \
            "the upstream node minted its own id instead of using the relay's"
    finally:
        b.stop_all()


@pytest.mark.parametrize("msg_type", [HiveMessageType.QUERY, HiveMessageType.CASCADE])
def test_empty_ids_count_as_absent(msg_type):
    b, r0 = _topology()
    b.start_all()
    try:
        master = b.get_master("M0").hm_protocol
        asker = b.get_satellite("asker")
        _send_without_metadata(asker, msg_type,
                               {"query_id": "", "originator_peer": ""})

        assert _wait(lambda: master._outstanding_queries, timeout=30.0), \
            "the upstream node never received the request"
        (upstream_id, _), = master._outstanding_queries.items()
        (relay_id, (relay_peer, _)), = r0.hm_protocol._outstanding_queries.items()
        assert relay_id, "the relay bound the empty query_id"
        assert relay_peer == asker.peer
        assert upstream_id == relay_id
    finally:
        b.stop_all()


def test_query_without_query_id_is_answered_through_a_relay():
    b, _ = _topology()
    b.start_all()
    try:
        _answer_upstream(b.get_master("M0"))
        asker = b.get_satellite("asker")
        _send_without_metadata(asker, HiveMessageType.QUERY)

        def answers():
            return asker.recorder.received(HiveMessageType.QUERY.value, direction="in")

        assert _wait(answers, timeout=20.0), \
            "a QUERY without query_id got no answer through the relay"
        assert answers()[0].payload["payload"]["data"]["utterance"] == "upstream answer"
    finally:
        b.stop_all()
