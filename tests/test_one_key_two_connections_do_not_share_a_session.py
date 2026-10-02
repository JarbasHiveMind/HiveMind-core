"""Two live connections on one access key never share a Layer-1 session.

T-6696, a regression from #299, found by reviewer-b and confirmed independently
by this lane. HIVEMIND-BRIDGE-1 §4 states what the Layer-1 session id is derived
from: "the connection's own identity (§3), which the server already guarantees
distinct, and the `session_id` the client declared. Namespacing the client's name
by the connection makes the result unique across all live connections -- two
connections that chose the same name still get different Layer-1 sessions". The
inbound MUST follows: "Two connections that named the same session thus never
resolve to the same Layer-1 identity -- isolation holds by construction, not by
hoping peers pick distinct names."

#299 keyed the namespace on the durable DB row instead, to keep it stable across
a reconnect. Two satellites sharing one household access key then resolved the
same declared session name to the same Layer-1 id, and the orchestrator merged
them into one conversation -- the second peer reading and writing the first's
state, which is the consequence §4 itself names. The peer ids stayed distinct
because `handle_hello_message` appends a collision suffix, so replies reached the
right socket and the logs looked right. That is why it was invisible.

The durability goal is not outweighed here, it is forbidden: HIVEMIND-AGENT-1
§3.3 says a server "MUST NOT select a different peer to receive the response by
any identity other than the `destination` -- in particular not by a shared
session namespace, a shared credential, or a shared site". The clause is §3.3 on
`architecture` dev today; architecture#35, which folds §3.3's duties into §3.2,
is still open, and the text of the prohibition is the same in both.
"""
from unittest.mock import MagicMock

from ovos_bus_client.session import Session

from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)

ONE_ACCESS_KEY = "one-household-key"
SHARED_ROW_ID = 7


def _protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.get_bus.return_value = agent.bus
    agent.callbacks = MagicMock()
    agent.plugin_id = "hivemind-ovos-agent-plugin"

    # ONE durable DB row: both connections present the same access key
    db_user = MagicMock()
    db_user.is_admin = False
    db_user.client_id = SHARED_ROW_ID
    db_user.allowed_types = ["speak", "recognizer_loop:utterance"]
    db_user.skill_blacklist = []
    db_user.intent_blacklist = []
    db_user.message_blacklist = []

    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user
    return HiveMindListenerProtocol(agent_protocol=agent, db=db)


def _conn(protocol, name, declared):
    client = HiveMindClientConnection(
        key=ONE_ACCESS_KEY,
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=protocol,
        sess=Session(session_id=declared),
    )
    client.name = name
    client.is_admin = False
    client.allowed_types = ["speak", "recognizer_loop:utterance"]
    client.send = MagicMock()
    return client


def test_two_live_connections_naming_the_same_session_do_not_collapse():
    """The defect, in its per-message form: no shared configuration needed.

    The two connections are configured DIFFERENTLY -- kitchen and livingroom --
    and each sends one message declaring the same name. On the defective code
    both emitted the same Layer-1 id.
    """
    protocol = _protocol()
    a = _conn(protocol, "sat", "kitchen")
    b = _conn(protocol, "sat", "livingroom")

    la = protocol._layer1_session_id(a, False, "shared-name")
    lb = protocol._layer1_session_id(b, False, "shared-name")

    assert la != lb, (
        "two live connections on one access key resolved the same declared "
        "session name to the same Layer-1 session: the orchestrator merges the "
        "two devices into one conversation (BRIDGE-1 §4)")


def test_the_connection_level_form_does_not_collapse_either():
    """Both connections configured the SAME, which is the household case."""
    protocol = _protocol()
    a = _conn(protocol, "sat", "kitchen")
    b = _conn(protocol, "sat", "kitchen")

    assert (protocol._layer1_session_id(a, False, "kitchen")
            != protocol._layer1_session_id(b, False, "kitchen"))


def test_one_connection_keeps_its_own_session_stable():
    """The negative control that matters most: the fix must not break the
    ordinary case. One connection asking twice for the same name gets one id."""
    protocol = _protocol()
    a = _conn(protocol, "sat", "kitchen")

    first = protocol._layer1_session_id(a, False, "kitchen")
    second = protocol._layer1_session_id(a, False, "kitchen")

    assert first == second


def test_one_connection_keeps_its_declared_sessions_distinct():
    """§4 again: a bridge multiplexing end users over one connection maps each
    declared name to its own Layer-1 session, never collapsing them."""
    protocol = _protocol()
    a = _conn(protocol, "bridge", "boot")

    assert (protocol._layer1_session_id(a, False, "telegram-42")
            != protocol._layer1_session_id(a, False, "telegram-99"))


def test_different_names_on_one_key_still_differ():
    """The other negative control: the finding is not that everything differs
    for a trivial reason."""
    protocol = _protocol()
    a = _conn(protocol, "sat", "kitchen")

    assert (protocol._layer1_session_id(a, False, "kitchen")
            != protocol._layer1_session_id(a, False, "livingroom"))


def test_an_admin_still_bypasses_the_translation():
    """BRIDGE-1 §4.1 grants administrative standing an exemption from the
    translation in MUST language: an admin's declared name is stamped
    unchanged. This change must not touch that."""
    protocol = _protocol()
    a = _conn(protocol, "admin", "kitchen")

    assert protocol._layer1_session_id(a, True, "ops") == "ops"


def test_the_namespace_is_not_the_bare_connection_nonce():
    """Identity scoping is kept: the token is still node-salted and hashed
    over the durable row, so it is not enumerable and not linkable across
    nodes. It just carries the connection nonce as well."""
    protocol = _protocol()
    a = _conn(protocol, "sat", "kitchen")

    ns = a.session_namespace
    assert ns != a.conn_nonce
    assert len(ns) == 16
    assert all(c in "0123456789abcdef" for c in ns)


def test_a_reconnect_does_not_reuse_the_namespace():
    """Stated as a cell because it is a DELIBERATE behaviour change.

    The old token survived a reconnect on purpose, so a replayed message stayed
    deliverable. That is what merged two live connections. A response for a
    session whose connection is gone is logged and dropped under AGENT-1 §3.3
    (architecture#35 would move the duty to §3.2; it is open), which forbids
    selecting a receiver by a shared session namespace.
    """
    protocol = _protocol()
    first = _conn(protocol, "sat", "kitchen")
    before = protocol._layer1_session_id(first, False, "kitchen")

    # the satellite drops and comes back on a new connection, same key, same
    # declared name
    second = _conn(protocol, "sat", "kitchen")
    after = protocol._layer1_session_id(second, False, "kitchen")

    assert before != after

    # The VALUE, not merely that something changed. reviewer-b's caution: an
    # implementation returning a fresh random string on every CALL would pass a
    # bare inequality while being wrong. Each id must be the correct derivation
    # from its OWN connection's namespace, and must be stable when asked again.
    assert before == f"{first.session_namespace}:kitchen"
    assert after == f"{second.session_namespace}:kitchen"
    assert first.session_namespace != second.session_namespace
    assert protocol._layer1_session_id(second, False, "kitchen") == after, (
        "the namespace must be per-CONNECTION, not per-call")
