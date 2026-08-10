"""Response isolation for QUERY/CASCADE answers.

HIVEMIND-NODE-1 §5.2: "A chunk goes to the originator only, never to the
other downstream nodes of a relay."

HIVEMIND-AGENT-1 §3.2: "A peer MUST NOT receive a response generated for a
different peer."

A node routes a response to the originator if it is a direct client, else to
the downstream hop the request arrived on (the recorded route). When neither
resolves, the node does not know where the response belongs — it MUST drop it,
because delivering it anywhere else hands one peer's answer to its siblings.
"""
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindListenerProtocol


def _make_node(node_key: str = "pubkey-A") -> HiveMindListenerProtocol:
    node = object.__new__(HiveMindListenerProtocol)
    node.peer = "master:0.0.0.0"
    node.identity = MagicMock(public_key=node_key, site_id=None)
    node.clients = {}
    node.cascade_select_callback = None
    node._pending_cascades = {}
    return node


def _wire_peers(node, *peers):
    sent = {p: [] for p in peers}
    for p in peers:
        conn = MagicMock()
        conn.send = lambda m, *a, box=sent[p]: box.append(m)
        node.clients[p] = conn
    return sent


def _response(originator: str, route=None) -> HiveMessage:
    msg = HiveMessage(
        HiveMessageType.QUERY,
        payload=HiveMessage(HiveMessageType.BUS,
                            payload=Message("speak", {"utterance": "42"})),
        metadata={"query_id": "q1", "is_response": True,
                  "originator_peer": originator,
                  "responder_peer": "pubkey-Z"})
    if route:
        msg.replace_route(route)
    return msg


# --- the defect: an unresolvable return path must not be fanned out --------

def test_unresolvable_response_reaches_no_peer():
    """No originator, no usable route -> nobody gets the answer."""
    node = _make_node()
    sent = _wire_peers(node, "sibling::1", "sibling::2")

    node._route_query_response(_response("gone::9"), None)

    assert sent["sibling::1"] == [], "a sibling received another peer's answer"
    assert sent["sibling::2"] == [], "a sibling received another peer's answer"


def test_response_with_unknown_route_hops_reaches_no_peer():
    """A route naming only nodes we are not connected to is not a return path."""
    node = _make_node()
    sent = _wire_peers(node, "sibling::1", "sibling::2")

    node._route_query_response(
        _response("gone::9", route=[{"source": "pubkey-R", "targets": ["x"]}]),
        None)

    assert sent["sibling::1"] == []
    assert sent["sibling::2"] == []


def test_unresolvable_response_from_a_client_reaches_no_peer():
    """Same rule when the response arrives from a downstream peer."""
    node = _make_node()
    sent = _wire_peers(node, "responder::1", "sibling::2")
    client = MagicMock(peer="responder::1")

    node._route_query_response(_response("gone::9"), client)

    assert sent["responder::1"] == []
    assert sent["sibling::2"] == [], "a sibling received another peer's answer"


# --- positive controls: legitimate responses still get delivered -----------

def test_direct_originator_still_receives_the_response():
    node = _make_node()
    sent = _wire_peers(node, "asker::1", "sibling::2")

    node._route_query_response(_response("asker::1"), None)

    assert len(sent["asker::1"]) == 1
    assert sent["sibling::2"] == []


def test_route_walk_still_delivers_to_the_downstream_hop():
    """The originator sits behind a relay: the hop the request arrived on is
    recorded in the route and is the return path."""
    node = _make_node()
    sent = _wire_peers(node, "relay::1", "sibling::2")

    node._route_query_response(
        _response("behind-relay::7",
                  route=[{"source": "relay::1", "targets": ["master:0.0.0.0"]}]),
        None)

    assert len(sent["relay::1"]) == 1, "route-walk return path stopped delivering"
    assert sent["sibling::2"] == []


def test_route_walk_does_not_send_the_response_back_to_its_sender():
    node = _make_node()
    sent = _wire_peers(node, "relay::1", "responder::2")
    client = MagicMock(peer="responder::2")

    node._route_query_response(
        _response("behind-relay::7",
                  route=[{"source": "responder::2", "targets": ["master:0.0.0.0"]},
                         {"source": "relay::1", "targets": ["master:0.0.0.0"]}]),
        client)

    assert len(sent["relay::1"]) == 1
    assert sent["responder::2"] == []
