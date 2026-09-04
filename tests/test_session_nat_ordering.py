"""``DefaultSessionPolicy`` denies a non-admin message whose ``session_id``
is the reserved, device-local ``"default"``. In the live call graph
``_install_client_session`` NATs that id to a per-connection Layer-1 id
(``"<nonce>:default"``) *before* ``handle_inject_agent_msg`` hands the
message to the policy chain (HIVEMIND-BRIDGE-1 §4/§4.1), so
``DefaultSessionPolicy`` is a defense-in-depth backstop, not the primary
gate, for non-admins today.

This test pins that ordering behaviorally: a non-admin "default" message
driven through ``handle_inject_agent_msg`` must be admitted (not denied
with ``session_id_default_forbidden``) because the session was already
rewritten by the time the policy chain reviews it. If a future refactor
ever moves the NAT after the policy chain, this test fails.
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
    db_user.allowed_types = ["recognizer_loop:utterance"]
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
    client.allowed_types = ["recognizer_loop:utterance"]
    client.send = MagicMock()
    return client


def test_non_admin_default_message_is_admitted_because_nat_precedes_policy():
    protocol = _make_protocol()
    client = _make_client(protocol)

    message = Message("recognizer_loop:utterance", {"utterances": ["hi"]},
                       {"session": {"session_id": "default"}})

    protocol.handle_inject_agent_msg(message, client)

    # not denied: no policy-denied notice sent to the client
    for call in client.send.call_args_list:
        payload = call.args[0]
        assert "session_id_default_forbidden" not in str(payload)

    # the message that reached the agent bus carries the NATted id, not
    # the bare, device-local "default"
    emitted = protocol.agent_protocol.bus.emit.call_args[0][0]
    session_id = emitted.context["session"]["session_id"]
    assert session_id != "default"
    assert session_id.endswith(":default")
