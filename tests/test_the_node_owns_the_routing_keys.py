"""The node owns the Layer-1 routing keys; a peer writes neither of them.

Miro's ruling, 2026-09-28: "source is stamped inbound with the unique peer id
core mints; destination is read only to core and becomes that same peer
automatically on the way out; a peer never controls either field. By
construction peers can't address anything: they send queries and get responses."

BRIDGE-1 3.1 makes the inbound ``source`` the node's to stamp and 3.2 makes the
outbound ``destination`` the node's to route on. Nothing authorizes the node to
write ``destination`` on the way IN with a service label, and nothing authorizes
a peer to write it at all. Before this, ``handle_inject_agent_msg`` wrote
``"audio"`` for a speak and ``"skills"`` otherwise, and kept a client's own value
when it sent one -- code from 2024-04 (5facb2c).

The value the node writes is a LABEL, not a routing key: ovos-core never reads
``destination``, and ovos-bus-client only swaps it with ``source`` in
``Message.reply()``, which is what carries the answer back to the peer this node
stamped as ``source``. So it names the agent plugin that handled the request.
"""
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from hivemind_core.policy import Verdict
from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)

_ALLOW = Verdict(denied=False)

VICTIM_PEER = "victim::session-b"


def _make_protocol(plugin_id="hivemind-ovos-agent-plugin"):
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.get_bus.return_value = agent.bus
    agent.callbacks = MagicMock()
    agent.plugin_id = plugin_id

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


def _chain_of(policy):
    """A PolicyChain holding one policy, built the way the runner expects.

    The node's own builtin policies are not in it: this cell is about whether
    the stamp survives a MUTATING policy, not about the builtins.
    """
    from hivemind_core.policy import PolicyChain
    return PolicyChain(policies=[policy])


def _inject(protocol, client, msg_type, destination=None, peer=None):
    context = {"session": {"session_id": "session-a"}}
    if destination is not None:
        context["destination"] = destination
    if peer is not None:
        context["peer"] = peer
    protocol.handle_inject_agent_msg(
        Message(msg_type, {"utterances": ["hi"]}, context), client)
    return protocol.agent_protocol.bus.emit.call_args[0][0]


def test_a_peer_id_a_client_wrote_does_not_reach_the_agent_bus():
    protocol = _make_protocol()
    client = _make_client(protocol)

    emitted = _inject(protocol, client, "recognizer_loop:utterance",
                      destination=VICTIM_PEER)

    assert emitted.context["destination"] == "hivemind-ovos-agent-plugin", (
        "a client named another connection's peer id and the node kept it: "
        "the agent-side key is the node's to write")


def test_a_peer_id_hidden_in_a_list_does_not_survive_either():
    protocol = _make_protocol()
    client = _make_client(protocol)

    # the peer id goes FIRST, so a fix that took the first entry, or dropped
    # only the entries it recognised, would still carry it
    emitted = _inject(protocol, client, "recognizer_loop:utterance",
                      destination=[VICTIM_PEER, "skills"])

    destination = emitted.context["destination"]
    assert isinstance(destination, str), "OVOS-MSG-1 3.3: a single string"
    assert destination == "hivemind-ovos-agent-plugin"


def test_the_stamped_destination_is_a_single_string_never_a_list():
    """OVOS-MSG-1 3.3: ``destination`` is a string.

    Inherited from `tests/test_inject_speak_destination.py`, which this change
    deletes. That file came from HiveMind-core#357 and its subject -- the node
    writing "audio" or "skills" -- is gone, but the shape requirement it fixed
    is not. It gets its own cell here so it cannot stop being checked while
    looking checked: #357 existed because the speak path stamped ["audio"], a
    LIST, where 3.3 allows one string and no multi-address form.

    Every path is covered, including the one a client tries to make a list.
    """
    protocol = _make_protocol()
    client = _make_client(protocol)

    cases = [
        ("speak", None),
        ("recognizer_loop:utterance", None),
        ("recognizer_loop:utterance", ["audio", "skills"]),
        ("recognizer_loop:utterance", [VICTIM_PEER]),
        ("speak", ["audio"]),
    ]
    for msg_type, destination in cases:
        emitted = _inject(protocol, client, msg_type, destination=destination)
        actual = emitted.context["destination"]
        assert isinstance(actual, str), (
            f"{msg_type} with destination={destination!r} emitted "
            f"{type(actual).__name__}, not a string (OVOS-MSG-1 3.3)")
        assert not isinstance(actual, list)


def test_a_service_label_a_client_wrote_is_dropped_too():
    # Not a security case, a design one: a peer addressing "skills" is a peer
    # addressing the agent bus, which it cannot do. Shipped clients write
    # "skills", "hive" and "HiveMind" here; none of them is honoured.
    protocol = _make_protocol()
    client = _make_client(protocol)

    for label in ("skills", "audio", "hive", "HiveMind"):
        emitted = _inject(protocol, client, "recognizer_loop:utterance",
                          destination=label)
        assert emitted.context["destination"] == "hivemind-ovos-agent-plugin"


def test_an_injected_speak_is_no_longer_readdressed_to_audio():
    # The 2024 code wrote "audio" so an injected speak would be said aloud by
    # the local audio stack. That is the node addressing a bus consumer on a
    # peer's behalf, which the ruling removes. The label now names the agent.
    protocol = _make_protocol()
    client = _make_client(protocol)

    emitted = _inject(protocol, client, "speak")

    assert emitted.context["destination"] == "hivemind-ovos-agent-plugin"


def test_an_admin_is_not_exempt():
    # The command chain has no permission table: a request upward is denied at
    # the first node above and an order downward is obeyed. An admin that must
    # address a connection has the administrative path, not a bus message.
    protocol = _make_protocol()
    client = _make_client(protocol, is_admin=True)

    emitted = _inject(protocol, client, "recognizer_loop:utterance",
                      destination=VICTIM_PEER)

    assert emitted.context["destination"] == "hivemind-ovos-agent-plugin"


def test_a_client_written_peer_key_does_not_survive_either():
    protocol = _make_protocol()
    client = _make_client(protocol)

    emitted = _inject(protocol, client, "recognizer_loop:utterance",
                      peer=VICTIM_PEER)

    assert emitted.context["peer"] == client.peer
    assert emitted.context["source"] == client.peer


def test_the_source_is_the_minted_peer_id_and_the_reply_returns_to_it():
    # BRIDGE-1 3.1 inbound, 3.2 outbound, in one cell: the node stamps source,
    # and Message.reply() swaps it into destination, which is what makes the
    # answer reach the peer that asked. No node code routes on a session id.
    protocol = _make_protocol()
    client = _make_client(protocol)

    emitted = _inject(protocol, client, "recognizer_loop:utterance",
                      destination=VICTIM_PEER)
    assert emitted.context["source"] == client.peer

    reply = emitted.reply("speak", {"utterance": "hello"})
    assert reply.context["destination"] == client.peer, (
        "the outbound key must be the peer the node stamped, not the string "
        "the client sent")
    assert VICTIM_PEER not in str(reply.context.get("destination"))


def test_a_metadata_transformer_cannot_put_a_peer_id_in_the_key():
    # The write sits AFTER the transformer chain, beside the source re-stamp,
    # because a transformer replaces context wholesale. A transformer that
    # returns destination=VICTIM is overwritten rather than obeyed.
    protocol = _make_protocol()
    client = _make_client(protocol)

    def _evil(message, _client):
        message.context = dict(message.context)
        message.context["destination"] = VICTIM_PEER
        message.context["source"] = VICTIM_PEER
        return message

    protocol._apply_utterance_transformers = _evil

    emitted = _inject(protocol, client, "recognizer_loop:utterance")

    assert emitted.context["destination"] == "hivemind-ovos-agent-plugin"
    assert emitted.context["source"] == client.peer


def test_a_policy_plugin_cannot_write_either_key_on_the_inject_path():
    """POLICY-1 lets a policy mutate the message; the stamp still wins.

    Asked for by reviewer-b: the ordering was measured to hold and nothing
    pinned it. The policy chain runs BEFORE the stamp on this path, so a policy
    that writes both keys during ``review`` is overwritten.
    """
    protocol = _make_protocol()
    client = _make_client(protocol)

    class _EvilPolicy:
        def review(self, message, client):
            message.context["destination"] = VICTIM_PEER
            message.context["source"] = VICTIM_PEER
            return _ALLOW

        def review_binary(self, payload, client):
            return _ALLOW

        def observe(self, message, client):
            return None

    protocol.policy_chain = _chain_of(_EvilPolicy())

    emitted = _inject(protocol, client, "recognizer_loop:utterance")

    assert emitted.context["destination"] == "hivemind-ovos-agent-plugin"
    assert emitted.context["source"] == client.peer


def test_a_policy_plugin_cannot_write_either_key_on_the_query_path():
    """The same on `_admit_for_query`, which is why that write moved too.

    This path has no transformer chain -- `_apply_utterance_transformers` runs
    on the injection path only -- so the policy chain is the only writer
    between admission and the stamp. Moving the write back above
    `policy_chain.review` passes the whole suite without this cell.
    """
    protocol = _make_protocol()
    client = _make_client(protocol)

    class _EvilPolicy:
        def review(self, message, client):
            message.context["destination"] = VICTIM_PEER
            message.context["source"] = VICTIM_PEER
            return _ALLOW

        def review_binary(self, payload, client):
            return _ALLOW

        def observe(self, message, client):
            return None

    protocol.policy_chain = _chain_of(_EvilPolicy())

    admitted = protocol._admit_for_query(
        Message("recognizer_loop:utterance", {"utterances": ["hi"]},
                {"session": {"session_id": "session-a"}}), client)

    assert admitted is not None
    assert admitted.context["destination"] == "hivemind-ovos-agent-plugin"
    assert admitted.context["source"] == client.peer


def test_a_non_string_plugin_id_is_coerced():
    """OVOS-MSG-1 3.3 wants a string and the annotation does not enforce one.

    Not reachable through the factory today. It WAS reachable while
    hivemind-plugin-manager#65 could bind a positional argument into the field,
    which is how reviewer-b found it. Hardening, with a cell so it stays fixed.
    """
    protocol = _make_protocol(plugin_id=object())
    client = _make_client(protocol)

    emitted = _inject(protocol, client, "recognizer_loop:utterance")

    assert isinstance(emitted.context["destination"], str)


def test_an_agent_without_a_recorded_plugin_id_gets_the_generic_label():
    # hivemind-plugin-manager records the entry-point name on the instance.
    # An agent built directly records nothing, and the node must still write a
    # label rather than leave the key absent or invent a class name.
    protocol = _make_protocol(plugin_id="")
    client = _make_client(protocol)

    emitted = _inject(protocol, client, "recognizer_loop:utterance",
                      destination=VICTIM_PEER)

    assert emitted.context["destination"] == "hivemind"
