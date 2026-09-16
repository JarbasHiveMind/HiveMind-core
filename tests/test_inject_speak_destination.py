"""OVOS-MSG-1 §3.3: ``destination`` is a string.

    "`destination` — string — opaque identifier of the intended consumer.
    ... A Message addresses one consumer or all of them; there is no
    multi-address form."

``handle_inject_agent_msg`` stamps a routing label onto every injected
message. The ``speak`` path used to stamp ``["audio"]`` while the other path
in the same function stamped ``"skills"``. Both paths now stamp a string.
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


def _make_client(protocol):
    client = HiveMindClientConnection(
        key="test-key",
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=protocol,
        sess=Session(session_id="default"),
    )
    client.name = "test-client"
    client.is_admin = False
    client.allowed_types = ["speak", "recognizer_loop:utterance"]
    client.send = MagicMock()
    return client


def _emitted(protocol):
    return protocol.agent_protocol.bus.emit.call_args[0][0]


def test_injected_speak_destination_is_the_string_audio():
    protocol = _make_protocol()
    client = _make_client(protocol)

    protocol.handle_inject_agent_msg(
        Message("speak", {"utterance": "hi"},
                {"session": {"session_id": "default"}}), client)

    destination = _emitted(protocol).context["destination"]
    assert isinstance(destination, str)
    assert destination == "audio"


def test_injected_default_destination_is_the_string_skills():
    protocol = _make_protocol()
    client = _make_client(protocol)

    protocol.handle_inject_agent_msg(
        Message("recognizer_loop:utterance", {"utterances": ["hi"]},
                {"session": {"session_id": "default"}}), client)

    destination = _emitted(protocol).context["destination"]
    assert isinstance(destination, str)
    assert destination == "skills"


def test_injected_explicit_destination_is_kept():
    protocol = _make_protocol()
    client = _make_client(protocol)

    protocol.handle_inject_agent_msg(
        Message("recognizer_loop:utterance", {"utterances": ["hi"]},
                {"destination": "my-consumer",
                 "session": {"session_id": "default"}}), client)

    assert _emitted(protocol).context["destination"] == "my-consumer"
