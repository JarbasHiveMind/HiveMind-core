"""A client does not write the agent-side routing key.

HIVEMIND-MSG-1 §5.2 states the rule for the QUERY path: ``originator_peer``
and ``route`` are "provenance a node records, not authorization", and an
answer goes only to the server-observed peer the request arrived on. The BUS
injection path had no such rule, so ``context["destination"]`` -- which the
client writes and this fleet's own relay routes on -- selected a connection.

``destination`` is opaque to OVOS: ovos-core never reads it, and
ovos-bus-client only swaps it with ``source`` in ``Message.reply()``. The one
consumer is the agent plugin's relay, which delivers to the connection whose
peer id the key names. So a client naming another connection's peer id had the
node speak, or answer, through that connection.

The fix keeps service labels and drops anything in the peer-id namespace, so
it needs no table of who is connected and no exemption for anyone.
"""
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)

VICTIM_PEER = "victim::session-b"


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.get_bus.return_value = agent.bus
    agent.callbacks = MagicMock()

    db_user = MagicMock()
    db_user.is_admin = False
    db_user.allowed_types = ["speak", "recognizer_loop:utterance"]
    db_user.skill_blacklist = []
    db_user.intent_blacklist = []
    db_user.message_blacklist = []

    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    return HiveMindListenerProtocol(agent_protocol=agent, db=db)


def _make_client(protocol, is_admin=False):
    client = HiveMindClientConnection(
        key="test-key",
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=protocol,
        sess=Session(session_id="session-a"),
    )
    client.name = "attacker"
    client.is_admin = is_admin
    client.allowed_types = ["speak", "recognizer_loop:utterance"]
    client.send = MagicMock()
    return client


def _inject(protocol, client, msg_type, destination):
    context = {"session": {"session_id": "session-a"}}
    if destination is not None:
        context["destination"] = destination
    protocol.handle_inject_agent_msg(
        Message(msg_type, {"utterances": ["hi"]}, context), client)
    return protocol.agent_protocol.bus.emit.call_args[0][0]


def test_a_peer_id_destination_does_not_reach_the_agent_bus():
    protocol = _make_protocol()
    client = _make_client(protocol)

    emitted = _inject(protocol, client, "recognizer_loop:utterance",
                      VICTIM_PEER)

    assert emitted.context["destination"] == "skills", (
        "a client named another connection's peer id and the node relayed to "
        "it: the agent-side routing key is the server's to write")


def test_a_peer_id_hidden_in_a_list_does_not_survive_either():
    protocol = _make_protocol()
    client = _make_client(protocol)

    # the peer id goes FIRST, so a fix that merely takes the first entry
    # would still deliver it; only dropping the namespace passes this
    emitted = _inject(protocol, client, "recognizer_loop:utterance",
                      [VICTIM_PEER, "skills"])

    destination = emitted.context["destination"]
    assert isinstance(destination, str), "OVOS-MSG-1 §3.3: a string"
    assert "::" not in destination
    assert destination == "skills"


def test_an_admin_is_not_exempt():
    # The command chain has no permission table: a request upward is denied at
    # the first node above and an order downward is obeyed. An admin that must
    # address a connection has the administrative path, not a bus message.
    protocol = _make_protocol()
    client = _make_client(protocol, is_admin=True)

    emitted = _inject(protocol, client, "recognizer_loop:utterance",
                      VICTIM_PEER)

    assert emitted.context["destination"] == "skills"


def test_a_service_label_is_still_honoured():
    protocol = _make_protocol()
    client = _make_client(protocol)

    emitted = _inject(protocol, client, "recognizer_loop:utterance",
                      "enclosure")

    assert emitted.context["destination"] == "enclosure", (
        "only the peer-id namespace is refused; a label addresses a consumer "
        "as before")


def test_an_injected_speak_is_still_forced_to_audio():
    protocol = _make_protocol()
    client = _make_client(protocol)

    emitted = _inject(protocol, client, "speak", VICTIM_PEER)

    assert emitted.context["destination"] == "audio"


def test_a_missing_destination_is_still_skills():
    protocol = _make_protocol()
    client = _make_client(protocol)

    emitted = _inject(protocol, client, "recognizer_loop:utterance", None)

    assert emitted.context["destination"] == "skills"


def test_a_non_string_entry_does_not_crash_the_admission():
    protocol = _make_protocol()
    client = _make_client(protocol)

    emitted = _inject(protocol, client, "recognizer_loop:utterance",
                      [None, 7, VICTIM_PEER])

    assert emitted.context["destination"] == "skills"
