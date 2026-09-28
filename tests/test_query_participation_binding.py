"""Participation binding for QUERY/CASCADE answer routing (HIVEMIND-MSG-1 §5.2).

A node MUST route a QUERY/CASCADE answer ONLY back to the SERVER-OBSERVED
connection the matching request arrived on — the return path it recorded when
it admitted the request. Client-supplied fields (``originator_peer``, the
message ``route``) may only SELECT a candidate connection; the recorded return
path AUTHORIZES the actual send. An answer for a request this node never
admitted (forged, or arrived after the retention TTL) is dropped.

This closes two forgery vectors an existence-only check would miss:

* self-record — an attacker sends a QUERY/CASCADE *request* claiming a victim's
  ``originator_peer`` (which would record that victim), then an ``is_response``
  for the same ``query_id``; and
* crafted-route — an attacker plants a victim hop in the response ``route`` so
  the route-walk delivers to the victim.

In both, the recorded return path is the attacker's own arriving connection,
never the victim, so the send is refused.
"""
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import (HiveMindClientConnection,
                                     HiveMindListenerProtocol)


def _make_node(node_key: str = "master-pubkey") -> HiveMindListenerProtocol:
    node = object.__new__(HiveMindListenerProtocol)
    node.peer = "master:0.0.0.0"
    node.identity = MagicMock(public_key=node_key, site_id=None)
    node.clients = {}
    node.cascade_select_callback = None
    node.illegal_callback = None
    node._pending_cascades = {}
    node._upstream_hm = None
    # stubs shared by the request-admission path in these unit tests
    node._unpack_message = MagicMock(
        return_value=Message("recognizer_loop:utterance", {"utterances": ["hi"]}))
    node.get_bus = MagicMock(return_value=MagicMock())
    node._answer_query_locally = MagicMock(return_value=False)
    return node


def _make_client(peer, **flags):
    client = MagicMock()
    client.peer = peer
    client.can_escalate = flags.get("can_escalate", False)
    client.can_propagate = flags.get("can_propagate", False)
    return client


def _wire(node, peer):
    conn = MagicMock()
    conn.peer = peer
    conn.send = MagicMock()
    node.clients[peer] = conn
    return conn


def _response(msg_type, originator_peer, query_id, route=None):
    inner = HiveMessage(HiveMessageType.BUS,
                        payload=Message("speak", {"utterance": "the answer"}))
    msg = HiveMessage(msg_type, payload=inner,
                      metadata={"query_id": query_id,
                                "originator_peer": originator_peer,
                                "responder_peer": "responder::9",
                                "is_response": True})
    if route:
        msg.replace_route(route)
    return msg


def _request(msg_type, originator_peer, query_id):
    inner = HiveMessage(HiveMessageType.BUS,
                        payload=Message("recognizer_loop:utterance",
                                        {"utterances": ["what time is it"]}))
    return HiveMessage(msg_type, payload=inner,
                       metadata={"query_id": query_id,
                                 "originator_peer": originator_peer})


# --- forgery: self-record --------------------------------------------------

def test_self_record_forgery_is_dropped():
    """An attacker sends a QUERY *request* claiming the victim as originator,
    then an is_response for the same query_id. The node bound the query to the
    attacker's arriving connection, not the claimed victim, so the answer is
    refused delivery to the victim."""
    node = _make_node()
    attacker = _make_client("attacker::1", can_escalate=True)
    victim_conn = _wire(node, "victim::1")

    # request claims the victim as originator (this is the self-record attempt)
    node.handle_query_message(
        _request(HiveMessageType.QUERY, "victim::1", "forge-q"), attacker)
    # forged answer for the same query_id, addressed to the victim
    node.handle_query_message(
        _response(HiveMessageType.QUERY, "victim::1", "forge-q"), attacker)

    victim_conn.send.assert_not_called()


def test_self_record_cascade_forgery_is_dropped():
    node = _make_node()
    attacker = _make_client("attacker::1", can_propagate=True)
    victim_conn = _wire(node, "victim::1")
    node._is_routing_loop = MagicMock(return_value=False)
    node._append_self_hop = MagicMock()
    node._rewrap = MagicMock(
        return_value=_request(HiveMessageType.CASCADE, "victim::1", "forge-c"))
    node.cascade_to_master = MagicMock()

    node.handle_cascade_message(
        _request(HiveMessageType.CASCADE, "victim::1", "forge-c"), attacker)
    # note: the CASCADE *request* legitimately fans out to the victim as a
    # downstream peer; the forgery is the ANSWER, which must never be delivered.
    forged_answer = _response(HiveMessageType.CASCADE, "victim::1", "forge-c")
    node.handle_cascade_message(forged_answer, attacker)

    delivered = [c.args[0] for c in victim_conn.send.call_args_list]
    assert forged_answer not in delivered
    assert not any((m.metadata or {}).get("is_response") for m in delivered)


# --- forgery: crafted route ------------------------------------------------

def test_crafted_route_forgery_is_dropped():
    """An attacker self-records a query_id, then sends an is_response whose
    route names the victim as a hop and whose originator_peer is not directly
    connected. The route-walk must refuse the victim: it is not the recorded
    return path."""
    node = _make_node()
    attacker = _make_client("attacker::1", can_escalate=True)
    victim_conn = _wire(node, "victim::1")

    # request records query_id -> attacker's arriving connection
    node.handle_query_message(
        _request(HiveMessageType.QUERY, "ghost::0", "route-q"), attacker)
    # forged answer: originator not connected, route plants the victim as a hop
    node.handle_query_message(
        _response(HiveMessageType.QUERY, "ghost::0", "route-q",
                  route=[{"source": "victim::1", "targets": ["master:0.0.0.0"]}]),
        attacker)

    victim_conn.send.assert_not_called()


# --- legit single-node round trip ------------------------------------------

def test_legit_query_answer_routes_to_the_recorded_return_path():
    node = _make_node()
    asker = _make_client("asker::1", can_escalate=True)
    originator_conn = _wire(node, "asker::1")

    node.handle_query_message(
        _request(HiveMessageType.QUERY, "asker::1", "q-rt"), asker)
    assert node._outstanding_return_path("q-rt") == "asker::1"

    responder = _make_client("responder::9", can_escalate=True)
    answer = _response(HiveMessageType.QUERY, "asker::1", "q-rt")
    node.handle_query_message(answer, responder)

    originator_conn.send.assert_called_once_with(answer)


# --- legit multi-hop relay: request from a downstream peer -----------------

def test_legit_multihop_answer_routes_back_to_the_downstream_hop():
    """The originator sits behind a downstream relay N. The request arrives
    from N (records N as the return path); the answer, addressed to the
    originator behind N, walks the route back to N."""
    node = _make_node()
    relay = _make_client("relay::1", can_escalate=True)
    relay_conn = _wire(node, "relay::1")

    node.handle_query_message(
        _request(HiveMessageType.QUERY, "behind-relay::7", "q-hop"), relay)
    assert node._outstanding_return_path("q-hop") == "relay::1"

    responder = _make_client("responder::9", can_escalate=True)
    answer = _response(HiveMessageType.QUERY, "behind-relay::7", "q-hop",
                       route=[{"source": "relay::1",
                               "targets": ["master:0.0.0.0"]}])
    node.handle_query_message(answer, responder)

    relay_conn.send.assert_called_once_with(answer)


# --- master-originated response still drops (behavior unchanged) -----------

def test_master_originated_query_response_still_drops():
    node = _make_node()
    node._relay_downstream = MagicMock()
    victim_conn = _wire(node, "leaf::1")

    # a request relayed FROM the master binds no downstream return path here
    node.query_from_master(_request(HiveMessageType.QUERY, "leaf::1", "q-m"))
    node._relay_downstream.assert_called_once()
    assert node._outstanding_return_path("q-m") is None

    node.query_from_master(_response(HiveMessageType.QUERY, "leaf::1", "q-m"))
    victim_conn.send.assert_not_called()


def test_master_originated_cascade_response_still_drops():
    node = _make_node()
    node._relay_downstream = MagicMock()
    victim_conn = _wire(node, "leaf::1")

    node.cascade_from_master(_request(HiveMessageType.CASCADE, "leaf::1", "c-m"))
    assert node._outstanding_return_path("c-m") is None

    node.cascade_from_master(_response(HiveMessageType.CASCADE, "leaf::1", "c-m"))
    victim_conn.send.assert_not_called()


# --- CASCADE local answer still delivered ----------------------------------

def test_cascade_local_answer_is_delivered_not_self_dropped():
    """The CASCADE local answer routes THROUGH _route_query_response; the
    request binds the return path first, so the node's own answer reaches the
    genuine originator."""
    node = _make_node()
    asker = _make_client("asker::1", can_propagate=True)
    originator_conn = _wire(node, "asker::1")
    node._is_routing_loop = MagicMock(return_value=False)
    node._append_self_hop = MagicMock()
    node._rewrap = MagicMock(
        return_value=_request(HiveMessageType.CASCADE, "asker::1", "cq"))
    node.cascade_to_master = MagicMock()

    def _local_answer(message, client, query_id, originator_peer, msg_type,
                      route, send_fn):
        send_fn(_response(msg_type, originator_peer, query_id))
        return True

    node._answer_query_locally = _local_answer

    node.handle_cascade_message(
        _request(HiveMessageType.CASCADE, "asker::1", "cq"), asker)

    originator_conn.send.assert_called_once()


# --- CASCADE collector runs only at the true origin ------------------------

def test_cascade_collector_runs_only_when_this_node_is_the_origin():
    """The select callback collects here only when the direct originator
    connection is the recorded return path (this node is the true origin)."""
    node = _make_node()
    asker = _make_client("asker::1", can_propagate=True)
    originator_conn = _wire(node, "asker::1")
    collected = []
    node.cascade_select_callback = lambda qid, responses: collected.append(qid)
    node.get_bus = MagicMock(return_value=MagicMock())

    # the origin admitted the request from asker -> return path is asker
    node._record_outstanding_query("cq2", "asker::1")
    node._route_query_response(
        _response(HiveMessageType.CASCADE, "asker::1", "cq2"), None)

    assert collected == ["cq2"]
    assert "cq2" in node._pending_cascades


def test_cascade_collector_not_triggered_for_forged_originator():
    """A forged originator_peer pointing at a connected victim must not trigger
    the collector for that victim (the return path is not the victim)."""
    node = _make_node()
    victim_conn = _wire(node, "victim::1")
    collected = []
    node.cascade_select_callback = lambda qid, responses: collected.append(qid)
    node.get_bus = MagicMock(return_value=MagicMock())

    # the request actually arrived on the attacker's connection
    node._record_outstanding_query("cq3", "attacker::1")
    node._route_query_response(
        _response(HiveMessageType.CASCADE, "victim::1", "cq3"), None)

    assert collected == []
    victim_conn.send.assert_not_called()


# --- originator disconnect purges its entries ------------------------------

def test_disconnect_purges_entries_bound_to_that_connection():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.get_bus.return_value = MagicMock()
    agent.callbacks = MagicMock()

    db_user = MagicMock()
    db_user.allowed_types = ["recognizer_loop:utterance"]
    db_user.is_admin = False
    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    node = HiveMindListenerProtocol(agent_protocol=agent, db=db)
    client = HiveMindClientConnection(
        key="test-key", send_msg=MagicMock(), disconnect=MagicMock(),
        hm_protocol=node, sess=Session("a-session"))
    client.name = "leaf"
    peer = client.peer

    node._record_outstanding_query("q1", peer)
    node._record_outstanding_query("q2", peer)
    node._record_outstanding_query("q3", "other::2")

    node.handle_client_disconnected(client)

    assert node._outstanding_return_path("q1") is None
    assert node._outstanding_return_path("q2") is None
    assert node._outstanding_return_path("q3") == "other::2"


# --- first-writer-wins: a live query_id can not be rebound ------------------

def test_first_writer_wins_prevents_return_path_rebinding():
    node = _make_node()
    node._record_outstanding_query("dup", "asker::1")
    node._record_outstanding_query("dup", "attacker::1")
    assert node._outstanding_return_path("dup") == "asker::1"
