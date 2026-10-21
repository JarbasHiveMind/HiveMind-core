"""Outbound session_id un-NAT at the bridge (HIVEMIND-BRIDGE-1 §4).

The symmetric counterpart of the inbound NAT (see ``test_session_nat``): the
bus stamps every inbound BUS message with the Layer-1 id
``f"{session_namespace}:{declared}"``. On the way back to the client,
``HiveMindClientConnection.send`` must strip this connection's namespace prefix
so the client only ever sees its OWN declared session_id — the internal
namespace never crosses the wire. Living in core means every agent/binary
protocol plugin inherits it instead of reimplementing an outbound un-NAT.

The un-NAT works on a per-peer deepcopy: the input message is shared across a
fan-out to multiple peers and must never be mutated.
"""
import json
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.get_bus.return_value = agent.bus
    db = MagicMock()
    return HiveMindListenerProtocol(agent_protocol=agent, db=db)


def _make_client(namespace, key="k", name="sat"):
    client = HiveMindClientConnection(
        key=key,
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=_make_protocol(),
        sess=Session(session_id="default"),
    )
    client.name = name
    # pin the namespace deterministically (per instance, so two clients in one
    # test keep distinct namespaces) instead of the db-derived derivation
    client.__class__ = type(
        "PinnedNamespaceConnection", (HiveMindClientConnection,),
        {"session_namespace": property(lambda self, _ns=namespace: _ns)})
    return client


def _sent_session_id(client):
    """The session_id in the payload actually handed to the transport."""
    payload = client.send_msg.call_args[0][0]
    data = json.loads(payload)
    # HiveMessage.serialize wraps the bus payload under "payload"
    inner = data.get("payload", data)
    return inner["context"]["session"]["session_id"]


def _bus_msg(session_id):
    return HiveMessage(
        HiveMessageType.BUS,
        payload=Message("speak", {"utterance": "hi"},
                        {"session": {"session_id": session_id}}),
    )


def test_namespaced_session_is_unnatted_and_input_not_mutated():
    # FAIL-BEFORE case: a namespaced Layer-1 id must reach the client stripped
    # back to its declared form, AND the shared input message must be untouched.
    client = _make_client("ns1")
    msg = _bus_msg("ns1:default")

    client.send(msg)

    assert _sent_session_id(client) == "default"
    # per-peer copy: the shared input still carries the NATted id
    assert msg.payload.context["session"]["session_id"] == "ns1:default"


def test_two_namespaces_no_cross_contamination():
    a = _make_client("nsA", key="a", name="a")
    b = _make_client("nsB", key="b", name="b")

    # a's own message and b's own message, each namespaced for that peer
    a.send(_bus_msg("nsA:default"))
    b.send(_bus_msg("nsB:kitchen"))

    assert _sent_session_id(a) == "default"
    assert _sent_session_id(b) == "kitchen"


def test_non_matching_prefix_sent_unchanged():
    client = _make_client("ns1")
    # another client's namespace — leave untouched
    client.send(_bus_msg("other:default"))
    assert _sent_session_id(client) == "other:default"


def test_admin_bare_session_sent_unchanged():
    client = _make_client("ns1")
    client.send(_bus_msg("default"))
    assert _sent_session_id(client) == "default"


def test_empty_remainder_sent_unchanged():
    client = _make_client("ns1")
    client.send(_bus_msg("ns1:"))
    assert _sent_session_id(client) == "ns1:"


def test_plaintext_ignored_when_unnat_applied():
    # A fan-out caller may pass a pre-serialized plaintext computed from the
    # still-NATted shared message. When the un-NAT applies, that plaintext is
    # wrong for this peer and must be dropped in favour of the un-NATted copy.
    client = _make_client("ns1")
    msg = _bus_msg("ns1:default")
    stale_plaintext = msg.serialize()  # carries ns1:default

    client.send(msg, plaintext=stale_plaintext)

    assert _sent_session_id(client) == "default"


def test_hello_message_unchanged():
    client = _make_client("ns1")
    hello = HiveMessage(HiveMessageType.HELLO, payload={"foo": "bar"})
    client.send(hello)
    # delivered verbatim, no crash on a non-BUS payload
    assert client.send_msg.called
