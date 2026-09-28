"""A client addresses only its own connection (HIVEMIND-BRIDGE-1 §3).

The node stamps ``source`` and ``peer`` on every message a client injects, but
relays any Layer-1 message whose ``destination`` names one of its peers to that
peer (§3.2), and the client writes ``destination`` itself. The built-in
``PeerDestinationPolicy`` denies a non-admin message whose ``destination`` is
another live connection's peer id.

The two connections below announce the same name and declare the same session
id, as two installs of one app can. Their peer ids then differ only by the
suffix ``handle_hello_message`` appends on a collision, which is exactly the
case a check keyed on the announced name would get wrong.
"""
from unittest.mock import MagicMock

import pytest
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_core.policy import (PEER_DESTINATION_FORBIDDEN,
                                  PeerDestinationPolicy)
from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)

NAME = "KitchenSatellite"
SESSION = "s-1"
TYPES = ["recognizer_loop:utterance", "ovos.utterance.speak",
         "mycroft.volume.get.response"]


class _Row:
    def __init__(self, client_id, is_admin=False):
        self.client_id = client_id
        self.is_admin = is_admin
        self.allowed_types = list(TYPES)
        self.api_key = f"key-{client_id}"
        self.skill_blacklist = []
        self.intent_blacklist = []


class _DB:
    """Just enough of ClientDatabase for resolve_user: rows by key and id."""

    def __init__(self):
        self.rows = {}
        self.fail = False

    def get_client_by_api_key(self, key):
        if self.fail:
            raise ConnectionError("database unreachable")
        return self.rows.get(key)

    def refresh(self, client_id):
        if self.fail:
            raise ConnectionError("database unreachable")
        return next((r for r in self.rows.values() if r.client_id == client_id), None)


def _protocol(db):
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.get_bus.return_value = agent.bus
    agent.callbacks = MagicMock()
    return HiveMindListenerProtocol(agent_protocol=agent, db=db)


def _connect(protocol, db, client_id, is_admin=False):
    row = _Row(client_id, is_admin=is_admin)
    db.rows[row.api_key] = row
    client = HiveMindClientConnection(
        key=row.api_key, send_msg=MagicMock(), disconnect=MagicMock(),
        hm_protocol=protocol, sess=Session(session_id=SESSION))
    client.name = NAME
    client.is_admin = is_admin
    client.allowed_types = list(TYPES)
    client.send = MagicMock()
    protocol.handle_hello_message(
        HiveMessage(HiveMessageType.HELLO, {"session": client.sess.serialize()}),
        client)
    return client


@pytest.fixture
def hub():
    db = _DB()
    protocol = _protocol(db)
    first = _connect(protocol, db, 1)
    second = _connect(protocol, db, 2)
    # the precondition: one announced name, one declared session, two peers
    assert first.peer == f"{NAME}::{SESSION}"
    assert second.peer.startswith(f"{NAME}::{SESSION}::")
    return protocol, db, first, second


def _review(protocol, client, destination, msg_type="ovos.utterance.speak"):
    context = {"session": {"session_id": SESSION}}
    if destination is not None:
        context["destination"] = destination
    message = Message(msg_type, {"utterance": "open the front door"}, context)
    return PeerDestinationPolicy(hm_protocol=protocol).review(message, client)


# -- denied ----------------------------------------------------------------------

def test_a_client_may_not_address_another_connection(hub):
    protocol, _db, first, second = hub
    verdict = _review(protocol, second, first.peer)
    assert verdict.denied
    assert verdict.code == PEER_DESTINATION_FORBIDDEN
    assert verdict.data == {"destination": [first.peer]}


def test_neither_twin_may_address_the_other(hub):
    protocol, _db, first, second = hub
    assert _review(protocol, first, second.peer).code == PEER_DESTINATION_FORBIDDEN
    assert _review(protocol, second, first.peer).code == PEER_DESTINATION_FORBIDDEN


def test_one_foreign_entry_in_a_list_denies_the_message(hub):
    protocol, _db, first, second = hub
    verdict = _review(protocol, second, ["skills", second.peer, first.peer])
    assert verdict.code == PEER_DESTINATION_FORBIDDEN
    assert verdict.data == {"destination": [first.peer]}


def test_a_revoked_admin_loses_the_exemption_without_reconnecting(hub):
    """The connection still carries is_admin from when it connected; the
    database row no longer does, and the row is what counts."""
    protocol, db, first, second = hub
    second.is_admin = True
    db.rows[second.key].is_admin = False
    second.invalidate_user()
    assert _review(protocol, second, first.peer).code == PEER_DESTINATION_FORBIDDEN


def test_a_database_error_propagates_so_the_chain_fails_closed(hub):
    protocol, db, first, second = hub
    second.invalidate_user()
    db.fail = True
    with pytest.raises(ConnectionError):
        _review(protocol, second, first.peer)


# -- admitted --------------------------------------------------------------------

@pytest.mark.parametrize("destination", [
    None, "", "skills", "audio", "HiveMind", "hive", "ovos.gui",
    "skill-weather.openvoiceos", ["skills", "audio"],
])
def test_service_labels_pass(hub, destination):
    protocol, _db, _first, second = hub
    assert not _review(protocol, second, destination).denied


def test_a_client_may_address_itself(hub):
    protocol, _db, _first, second = hub
    assert not _review(protocol, second, second.peer).denied
    assert not _review(protocol, second, [second.peer, "skills"]).denied


def test_an_id_no_connection_holds_passes(hub):
    """Only this node's own connections are protected here: a relay's
    downstream peer id means nothing to this node and is not refused."""
    protocol, _db, first, second = hub
    assert not _review(protocol, second, f"{NAME}::{SESSION}::0000beef").denied
    assert not _review(protocol, second, "Downstream::s-9").denied


@pytest.mark.parametrize("destination", [7, {"peer": "x"}, [["nested"]], [None]])
def test_entries_that_cannot_be_a_peer_id_pass(hub, destination):
    protocol, _db, _first, second = hub
    assert not _review(protocol, second, destination).denied


def test_an_admin_may_address_another_connection(hub):
    protocol, db, first, second = hub
    db.rows[second.key].is_admin = True
    second.invalidate_user()
    assert not _review(protocol, second, first.peer).denied


def test_without_a_database_the_connection_snapshot_decides(hub):
    protocol, _db, first, second = hub
    protocol.db = None
    assert _review(protocol, second, first.peer).denied
    second.is_admin = True
    assert not _review(protocol, second, first.peer).denied


# -- through the node ------------------------------------------------------------

def _denials(client):
    return [call.args[0].payload for call in client.send.call_args_list
            if call.args[0].payload.msg_type == "hive.policy.denied"]


def test_the_node_never_emits_a_message_addressed_to_another_connection(hub):
    protocol, _db, first, second = hub
    bus = protocol.agent_protocol.bus
    message = Message("ovos.utterance.speak", {"utterance": "open the front door"},
                      {"destination": first.peer, "session": {"session_id": SESSION}})

    protocol.handle_inject_agent_msg(message, second)

    bus.emit.assert_not_called()
    first.send.assert_not_called()
    denied = _denials(second)
    assert [d.data["code"] for d in denied] == [PEER_DESTINATION_FORBIDDEN]
    assert denied[0].data["data"] == {"destination": [first.peer]}


def test_the_node_still_forwards_the_same_message_addressed_to_a_service(hub):
    protocol, _db, _first, second = hub
    bus = protocol.agent_protocol.bus
    message = Message("mycroft.volume.get.response", {"percent": 0.4},
                      {"destination": "HiveMind", "session": {"session_id": SESSION}})

    protocol.handle_inject_agent_msg(message, second)

    bus.emit.assert_called_once()
    assert bus.emit.call_args.args[0].context["peer"] == second.peer
    assert _denials(second) == []


def test_the_query_path_is_gated_too(hub):
    protocol, _db, first, second = hub
    message = Message("recognizer_loop:utterance", {"utterances": ["hi"]},
                      {"destination": first.peer, "session": {"session_id": SESSION}})

    assert protocol._admit_for_query(message, second) is None
    assert [d.data["code"] for d in _denials(second)] == [PEER_DESTINATION_FORBIDDEN]


def test_the_gate_is_built_in(hub):
    protocol, _db, _first, _second = hub
    assert isinstance(protocol.policy_chain.policies[2], PeerDestinationPolicy)
    assert protocol.policy_chain._optional[2] is False
