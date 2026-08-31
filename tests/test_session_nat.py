"""Inbound session_id NAT at the bridge (HIVEMIND-BRIDGE-1 §4).

``session_id`` is a Layer-1 (orchestrator) identity that OVOS
``SessionManager`` keys per-conversation state on. The client picks it
arbitrarily, so two connections that happen to choose the same value (two
satellites both using "default", or any shared name) must not resolve to the
same OVOS session — that would merge their converse/active-skill/dialog
state. ``_install_client_session`` must translate the client-chosen
``session_id`` to a per-connection Layer-1 id before the message reaches the
OVOS bus, while leaving every other session field untouched.

The Layer-1 id is derived as ``f"{conn_nonce}:{sess.session_id}"``, NOT
cached once per connection: session travels per message and the client
declares it (a peer may re-HELLO with a new session_id, and a bridge like
the baresip SIP gateway mints a fresh session_id per call on a single,
long-lived connection). Namespacing by the connection's own nonce keeps two
different connections that pick the same declared name apart, while letting
one connection's distinct declared sessions (a fresh call, a re-HELLO) stay
distinct from each other too.
"""
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.get_bus.return_value = agent.bus

    db = MagicMock()

    return HiveMindListenerProtocol(agent_protocol=agent, db=db,
                                    require_crypto=False,
                                    handshake_enabled=False)


def _make_client(sess, key="test-key", name="test-client"):
    client = HiveMindClientConnection(
        key=key,
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=_make_protocol(),
        sess=sess,
    )
    client.name = name
    return client


def _install(client, message):
    node = object.__new__(HiveMindListenerProtocol)
    return node._install_client_session(message, client)


def test_two_connections_same_session_id_get_distinct_layer1_sessions():
    first = _make_client(Session(session_id="shared"), key="key-1", name="sat-1")
    second = _make_client(Session(session_id="shared"), key="key-2", name="sat-2")

    msg1 = _install(first, Message("recognizer_loop:utterance",
                                    {"utterances": ["hi"]}))
    msg2 = _install(second, Message("recognizer_loop:utterance",
                                     {"utterances": ["hi"]}))

    sid1 = msg1.context["session"]["session_id"]
    sid2 = msg2.context["session"]["session_id"]

    assert sid1 != sid2
    assert sid1 == first.layer1_session_id
    assert sid2 == second.layer1_session_id


def test_layer1_session_id_is_stable_per_connection():
    client = _make_client(Session(session_id="shared"))

    msg1 = _install(client, Message("recognizer_loop:utterance",
                                     {"utterances": ["one"]}))
    msg2 = _install(client, Message("recognizer_loop:utterance",
                                     {"utterances": ["two"]}))

    sid1 = msg1.context["session"]["session_id"]
    sid2 = msg2.context["session"]["session_id"]

    assert sid1 == sid2 == client.layer1_session_id


def test_redeclared_session_gets_a_distinct_layer1_session():
    # A single connection may declare a new session_id mid-life — a re-HELLO,
    # or a bridge like baresip's SIP gateway that mints a fresh session_id
    # per call on one long-lived connection. Each declared session must get
    # its own Layer-1 id; caching the Layer-1 id once per connection would
    # wrongly collapse them into a single OVOS session.
    client = _make_client(Session(session_id="call-1"))

    msg1 = _install(client, Message("recognizer_loop:utterance",
                                     {"utterances": ["first call"]}))
    sid1 = msg1.context["session"]["session_id"]

    client.sess = Session(session_id="call-2")

    msg2 = _install(client, Message("recognizer_loop:utterance",
                                     {"utterances": ["second call"]}))
    sid2 = msg2.context["session"]["session_id"]

    assert sid1 != sid2
    nonce1, _, declared1 = sid1.partition(":")
    nonce2, _, declared2 = sid2.partition(":")
    assert nonce1 == nonce2 == client.conn_nonce
    assert declared1 == "call-1"
    assert declared2 == "call-2"


def test_session_contents_preserved():
    sess = Session(session_id="shared", lang="pt-pt")
    sess.intent_context["some_key"] = "some_value"
    client = _make_client(sess)

    message = _install(client, Message("recognizer_loop:utterance",
                                        {"utterances": ["hi"]}))

    session = message.context["session"]
    assert session["session_id"] == client.layer1_session_id
    assert session["session_id"] != "shared"
    assert session["lang"].lower() == "pt-pt"
    assert session["intent_context"]["some_key"] == "some_value"


def test_same_connection_different_named_payload_still_one_layer1_session():
    client = _make_client(Session(session_id="shared"))

    # a bus message arriving with a *different* session name already
    # attached to it (e.g. relayed/replayed) must still be re-stamped with
    # this connection's own Layer-1 id: the peer names its session at the
    # connection level, not per message.
    message = Message("recognizer_loop:utterance", {"utterances": ["hi"]},
                       {"session": {"session_id": "someone-elses-session"}})

    result = _install(client, message)

    assert result.context["session"]["session_id"] == client.layer1_session_id
    assert result.context["session"]["session_id"] != "someone-elses-session"
