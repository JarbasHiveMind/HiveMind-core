"""Regression tests: a client without escalate/propagate permission must not
be able to forge a QUERY/CASCADE "response" to smuggle an arbitrary payload
to an arbitrary peer.

``handle_query_message``/``handle_cascade_message`` used to check
``metadata.get("is_response")`` and dispatch straight to
``_route_query_response`` *before* the ``can_escalate``/``can_propagate``
gate that every request goes through. ``_route_query_response`` trusts
``metadata["originator_peer"]`` as a bare delivery address with no proof the
sender ever participated in that ``query_id`` — so an unprivileged client
could forge ``{"is_response": True, "originator_peer": <victim>}`` around any
payload and have it delivered verbatim to the victim's connection, bypassing
the ACL entirely (HIVEMIND-AGENT-1 §3.2). The permission check now runs
before the is_response branch, exactly like it already ran before the
request branch.
"""
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindListenerProtocol


def _make_protocol():
    proto = object.__new__(HiveMindListenerProtocol)
    proto.peer = "master:0.0.0.0"
    proto.identity = MagicMock(public_key="master-pubkey", site_id=None)
    proto.clients = {}
    proto.illegal_callback = MagicMock()
    proto.cascade_select_callback = None
    proto._pending_cascades = {}
    return proto


def _make_client(peer, **flags):
    client = MagicMock()
    client.peer = peer
    client.is_admin = flags.get("is_admin", False)
    client.can_propagate = flags.get("can_propagate", False)
    client.can_escalate = flags.get("can_escalate", False)
    return client


def _forged_response(msg_type, originator_peer, query_id="not-a-real-query"):
    inner = HiveMessage(HiveMessageType.BUS,
                        payload={"type": "speak",
                                 "data": {"utterance": "ATTACKER INJECTED THIS"},
                                 "context": {}})
    return HiveMessage(msg_type, payload=inner,
                       metadata={"query_id": query_id,
                                 "originator_peer": originator_peer,
                                 "responder_peer": "attacker::1",
                                 "is_response": True})


def _wire(proto, peer):
    conn = MagicMock()
    conn.send = MagicMock()
    proto.clients[peer] = conn
    return conn


# --- the defect: an unprivileged client must not be able to forge a response

def test_forged_query_response_from_unprivileged_client_is_dropped():
    proto = _make_protocol()
    attacker = _make_client("attacker::1", can_escalate=False)
    victim_conn = _wire(proto, "victim::1")

    proto.handle_query_message(
        _forged_response(HiveMessageType.QUERY, "victim::1"), attacker)

    victim_conn.send.assert_not_called()
    proto.illegal_callback.assert_called_once()
    attacker.disconnect.assert_called_once_with()


def test_forged_cascade_response_from_unprivileged_client_is_dropped():
    proto = _make_protocol()
    attacker = _make_client("attacker::1", can_propagate=False)
    victim_conn = _wire(proto, "victim::1")

    proto.handle_cascade_message(
        _forged_response(HiveMessageType.CASCADE, "victim::1"), attacker)

    victim_conn.send.assert_not_called()
    proto.illegal_callback.assert_called_once()
    attacker.disconnect.assert_called_once_with()


# --- positive control: a legitimate in-flight response must still land -----

def test_legitimate_query_response_still_reaches_its_originator():
    proto = _make_protocol()
    responder = _make_client("responder::1", can_escalate=True)
    originator_conn = _wire(proto, "originator::1")

    response = _forged_response(HiveMessageType.QUERY, "originator::1",
                                query_id="real-query-42")
    # simulate a genuinely privileged responder answering a real query
    response.metadata["responder_peer"] = responder.peer

    proto.handle_query_message(response, responder)

    originator_conn.send.assert_called_once_with(response)
    proto.illegal_callback.assert_not_called()
    responder.disconnect.assert_not_called()


def test_legitimate_cascade_response_still_reaches_its_originator():
    proto = _make_protocol()
    responder = _make_client("responder::1", can_propagate=True)
    originator_conn = _wire(proto, "originator::1")

    response = _forged_response(HiveMessageType.CASCADE, "originator::1",
                                query_id="real-query-42")
    response.metadata["responder_peer"] = responder.peer

    proto.handle_cascade_message(response, responder)

    originator_conn.send.assert_called_once_with(response)
    proto.illegal_callback.assert_not_called()
    responder.disconnect.assert_not_called()
