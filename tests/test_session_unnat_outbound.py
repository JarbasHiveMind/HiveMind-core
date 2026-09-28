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
import logging
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


def test_unnamespaced_prefix_sent_unchanged():
    # A colon-bearing session id that this node never namespaced. "other" is
    # not the shape a ``session_namespace`` token takes, so it is none of this
    # node's business and travels untouched. This is the pass-through case; the
    # drop case is a HEX-shaped foreign prefix, tested below — the two are
    # deliberately kept apart, because a test that spells a foreign namespace
    # "other" cannot see the defect at all.
    client = _make_client("ns1")
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


# --- AGENT-1 §3.3: a response whose peer is gone ---------------------------
#
# A delayed bus reply can outlive the connection it was generated for. The
# ``peer`` key is recycled on reconnect (the collision suffix is minted only
# against a LIVE connection, and a clean disconnect pops the old one first), so
# the stale reply is addressed to a live socket carrying ANOTHER connection's
# Layer-1 namespace. §3.3 forbids selecting the receiver "by any identity other
# than the ``destination`` — in particular not by a shared session namespace",
# and requires the undelivered response to be logged at WARNING.
#
# Before this guard the raw internal token went out on the wire, which also
# breaks the BRIDGE-1 §4 outbound MUST: the peer saw neither the name it used
# nor a stable id across turns.

_NS_A = "8a783b509a6d721a"   # 16 hex, the sha256(...)[:16] shape
_NS_B = "479902549eebbcfe"
_NS_FALLBACK = "0123456789abcdef0123456789abcdef"  # 32 hex, uuid4().hex shape


def test_reconnected_peer_does_not_receive_the_old_token():
    # THE CELL THE FINDING ASKS FOR. The reconnected connection holds namespace
    # _NS_B; a reply still carrying _NS_A arrives for it. It must receive
    # NOTHING — not the old token, and not a rewritten id either.
    client = _make_client(_NS_B)

    client.send(_bus_msg(f"{_NS_A}:chat"))

    assert not client.send_msg.called, (
        "a reply carrying another connection's Layer-1 namespace reached the "
        "peer; it must be dropped under HIVEMIND-AGENT-1 3.3")


def test_the_old_token_is_not_merely_rewritten():
    # Guards the weaker fix: stripping or replacing the foreign prefix would
    # hand the peer somebody else's conversation under its own name, which is
    # the §3.2 isolation break §3.3 exists to forbid. Nothing is sent at all.
    client = _make_client(_NS_B)
    client.send(_bus_msg(f"{_NS_A}:chat"))
    assert client.send_msg.call_args_list == []


def test_foreign_namespace_drop_is_logged_at_warning(caplog):
    # §3.3 makes the log the ONLY place the loss can appear ("no peer can
    # observe it"), so a silent drop is non-conformant. The record must name
    # the session and the destination it could not resolve.
    client = _make_client(_NS_B)
    msg = HiveMessage(
        HiveMessageType.BUS,
        payload=Message("speak", {"utterance": "hi"},
                        {"session": {"session_id": f"{_NS_A}:chat"},
                         "destination": "sat::chat"}),
    )

    with caplog.at_level(logging.WARNING, logger="hivemind_core.protocol"):
        client.send(msg)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "the undelivered response was dropped without a WARNING"
    text = warnings[0].getMessage()
    assert f"{_NS_A}:chat" in text, text      # the session it carried
    assert "sat::chat" in text, text          # the destination it names


def test_fallback_shaped_namespace_is_also_dropped():
    # ``session_namespace`` falls back to the bare uuid4().hex when no durable
    # client_id resolves (unauthenticated/edge). That token is 32 hex, not 16,
    # and a guard that only knows the 16-hex shape leaks on exactly the
    # connections that have no identity to scope them.
    client = _make_client(_NS_B)
    client.send(_bus_msg(f"{_NS_FALLBACK}:chat"))
    assert not client.send_msg.called


def test_own_namespace_still_delivered_after_the_guard():
    # The CONTROL for every drop above: the same code path, same shapes, this
    # connection's OWN prefix. If this reds, the guard has stopped the §4
    # outbound translation instead of narrowing it.
    client = _make_client(_NS_B)
    client.send(_bus_msg(f"{_NS_B}:chat"))
    assert _sent_session_id(client) == "chat"


def test_admin_hex_shaped_declared_id_is_not_dropped():
    # §4.1 exempts an admin from translation, so its declared id reaches the
    # bus unchanged and comes back unchanged. An admin that happens to name its
    # session with a hex-shaped prefix must not be mistaken for a foreign
    # namespace and silenced.
    client = _make_client(_NS_B)
    client.is_admin = True
    client.send(_bus_msg(f"{_NS_A}:chat"))
    assert _sent_session_id(client) == f"{_NS_A}:chat"


def test_client_declared_hex_shaped_name_round_trips():
    # The narrowest hole the shape test could open. A bridge may declare a
    # session name that itself looks like a namespace token ("0123...:call42").
    # Inbound it is NATted to "<ours>:0123...:call42", so outbound OUR prefix
    # matches FIRST and the client gets its own name back. The drop branch is
    # only reached when our prefix does not match at all, so a legitimate
    # hex-shaped declared name is never silenced.
    client = _make_client(_NS_B)
    client.send(_bus_msg(f"{_NS_B}:{_NS_A}:call42"))
    assert _sent_session_id(client) == f"{_NS_A}:call42"
