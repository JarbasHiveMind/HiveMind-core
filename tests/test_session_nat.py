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

from hivemind_bus_client.message import HiveMessage, HiveMessageType

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


def test_different_named_payload_gets_its_own_layer1_session():
    # Session travels PER MESSAGE and the client declares it (BRIDGE-1 §4).
    # A single connection may multiplex several declared sessions (a relay, or
    # a per-call bridge like baresip). A payload declaring its OWN session_id
    # must map to that declared id namespaced by the connection nonce —
    # ``nonce:declared`` — NOT collapse onto the connection's HELLO baseline.
    client = _make_client(Session(session_id="baseline"))

    message = Message("recognizer_loop:utterance", {"utterances": ["hi"]},
                       {"session": {"session_id": "call-42"}})

    result = _install(client, message)

    sid = result.context["session"]["session_id"]
    assert sid == f"{client.conn_nonce}:call-42"
    # the declared id is namespaced, never handed through raw
    assert sid != "call-42"
    # and it is NOT the baseline's id — the per-message session wins
    assert sid != f"{client.conn_nonce}:baseline"


def test_multiplexed_sessions_over_one_connection_stay_isolated():
    # DEFECT A: two DIFFERENT declared session_ids over ONE connection must
    # resolve to two DISTINCT Layer-1 ids, each ``nonce:declared``. Collapsing
    # them onto the connection baseline would merge a relay's / bridge's
    # independent conversations into one OVOS session.
    client = _make_client(Session(session_id="baseline"))

    a = _install(client, Message("recognizer_loop:utterance", {"utterances": ["a"]},
                                 {"session": {"session_id": "sess-A"}}))
    b = _install(client, Message("recognizer_loop:utterance", {"utterances": ["b"]},
                                 {"session": {"session_id": "sess-B"}}))

    sid_a = a.context["session"]["session_id"]
    sid_b = b.context["session"]["session_id"]

    assert sid_a == f"{client.conn_nonce}:sess-A"
    assert sid_b == f"{client.conn_nonce}:sess-B"
    assert sid_a != sid_b


def test_message_without_declared_session_uses_baseline_id():
    # The unchanged single-session path, pinned explicitly: a client that
    # declares no per-message session (or declares its own baseline id) gets
    # ``nonce:baseline_session_id``.
    client = _make_client(Session(session_id="baseline"))

    none_declared = _install(client, Message("recognizer_loop:utterance",
                                             {"utterances": ["hi"]}))
    same_declared = _install(client, Message("recognizer_loop:utterance",
                                             {"utterances": ["hi"]},
                                             {"session": {"session_id": "baseline"}}))

    assert none_declared.context["session"]["session_id"] == f"{client.conn_nonce}:baseline"
    assert same_declared.context["session"]["session_id"] == f"{client.conn_nonce}:baseline"


def test_rich_payload_location_overrides_baseline():
    # Contents merge lets a message's OWN present fields win over the baseline:
    # a rich payload declaring a new location overrides the HELLO baseline's
    # location on that message.
    baseline = Session(session_id="baseline", lang="de-DE")
    baseline.location_preferences = {"city": {"name": "Berlin"},
                                     "timezone": {"code": "Europe/Berlin"}}
    client = _make_client(baseline)

    message = Message("recognizer_loop:utterance", {"utterances": ["hi"]},
                       {"session": {"session_id": "baseline",
                                    "location": {"city": {"name": "Lisbon"},
                                                 "timezone": {"code": "Europe/Lisbon"}}}})

    result = _install(client, message)
    session = result.context["session"]
    assert session["location"]["timezone"]["code"] == "Europe/Lisbon"
    assert session["location"]["city"]["name"] == "Lisbon"


def test_thin_control_message_does_not_clobber_baseline_location():
    # DEFECT B (session-contents bleed): a thin control bus message (same
    # session_id, no location, lang: null) must NOT destroy the HELLO
    # baseline's location. The old code wholesale-replaced ``client.sess``
    # with a Session built from the thin payload, whose absent location was
    # fabricated from the master's own Configuration() default — so a German
    # satellite's Berlin location was silently replaced by the master default
    # and time queries answered hours off. The message's emitted session must
    # still carry Berlin, merged from the baseline.
    baseline = Session(session_id="sat-de", lang="de-DE")
    baseline.location_preferences = {"city": {"name": "Berlin"},
                                     "timezone": {"code": "Europe/Berlin"}}

    db = MagicMock()
    db.get_client_by_api_key.return_value = MagicMock(is_admin=False)
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.get_bus.return_value = agent.bus
    protocol = HiveMindListenerProtocol(agent_protocol=agent, db=db,
                                        require_crypto=False,
                                        handshake_enabled=False)
    protocol.policy_chain = MagicMock()
    protocol.policy_chain.review.return_value = MagicMock(denied=False)

    client = HiveMindClientConnection(
        key="k", send_msg=MagicMock(), disconnect=MagicMock(),
        hm_protocol=protocol, sess=baseline)
    client.name = "sat-de"
    client.allowed_types = ["mycroft.volume.get"]
    client.is_admin = False

    thin = Message("mycroft.volume.get", {},
                   {"session": {"session_id": "sat-de", "site_id": "default",
                                "lang": None}})
    protocol.handle_bus_message(HiveMessage(HiveMessageType.BUS, payload=thin),
                                client)

    # baseline was NOT mutated by the bus payload
    assert client.sess.location_preferences["timezone"]["code"] == "Europe/Berlin"

    emitted = agent.bus.emit.call_args[0][0]
    loc = emitted.context["session"]["location"]
    assert loc["timezone"]["code"] == "Europe/Berlin"
    assert loc["city"]["name"] == "Berlin"
    # and the message still got this connection's Layer-1 id
    assert emitted.context["session"]["session_id"] == f"{client.conn_nonce}:sat-de"
