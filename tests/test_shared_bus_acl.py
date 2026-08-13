"""SHARED_BUS carries client-chosen content, so it is admitted like BUS.

`shared_bus_callback` is a documented extension point — operators wire it to
logging, aggregation, or another system. Reaching it without the per-client
message-type allowlist made it a way around that allowlist, including for a
client whose allowlist is empty and which is therefore denied everything else.
"""
from unittest.mock import MagicMock

from ovos_bus_client.message import Message

from hivemind_core.protocol import HiveMindClientConnection, HiveMindListenerProtocol


def _protocol(allowed_types, **kwargs):
    """The policy re-reads the allowlist from the DB so a grant or revocation
    takes effect without a reconnect, so the DB row is what the test sets."""
    db_user = MagicMock()
    db_user.allowed_types = list(allowed_types)
    db_user.intent_blacklist = []
    db_user.skill_blacklist = []
    db_user.message_blacklist = []
    db_user.is_admin = False
    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user
    return HiveMindListenerProtocol(agent_protocol=MagicMock(), db=db, **kwargs)


def _client(protocol, allowed_types):
    client = HiveMindClientConnection(
        key="access-key", send_msg=MagicMock(), disconnect=MagicMock(),
        hm_protocol=protocol,
    )
    client.name = "sat"
    client.allowed_types = allowed_types
    client.intent_blacklist = []
    client.skill_blacklist = []
    client.message_blacklist = []
    client.is_admin = False
    return client


def test_a_type_the_client_may_not_send_does_not_reach_the_monitor_hook():
    protocol = _protocol(["recognizer_loop:utterance"])
    seen = []
    protocol.shared_bus_callback = seen.append
    client = _client(protocol, allowed_types=["recognizer_loop:utterance"])

    protocol.handle_client_shared_bus(
        Message("mycroft.skills.shutdown", {}), client)

    assert seen == [], "the allowlist must apply to SHARED_BUS too"


def test_an_empty_allowlist_denies_shared_bus_as_well():
    """An empty allowlist is deny-all; it must not leave one door open."""
    protocol = _protocol([])
    seen = []
    protocol.shared_bus_callback = seen.append
    client = _client(protocol, allowed_types=[])

    protocol.handle_client_shared_bus(Message("anything.at.all", {}), client)

    assert seen == []


def test_an_allowed_type_still_reaches_the_monitor_hook():
    """The control: gating must not disable passive bus sharing."""
    protocol = _protocol(["recognizer_loop:utterance"])
    seen = []
    protocol.shared_bus_callback = seen.append
    client = _client(protocol, allowed_types=["recognizer_loop:utterance"])

    protocol.handle_client_shared_bus(
        Message("recognizer_loop:utterance", {"utterances": ["hello"]}), client)

    assert len(seen) == 1
    assert seen[0].msg_type == "recognizer_loop:utterance"
