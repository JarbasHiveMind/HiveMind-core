"""Lifecycle telemetry must not block client handshakes or direct queries."""

import threading
from types import SimpleNamespace

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivemind_core.policy import PolicyChain
from hivemind_core.protocol import HiveMindListenerProtocol
from hivemind_plugin_manager.protocols import ClientCallbacks
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session


class _BrokenAgent:
    callbacks = ClientCallbacks()

    def __init__(self):
        self.get_bus_called = threading.Event()
        self.hm_protocol = None

    def get_bus(self, _client=None):
        self.get_bus_called.set()
        raise ConnectionError("agent bus unavailable")

    def answer_query(self, _utterance, _lang, client=None):
        yield "fast answer"


class _BinaryProtocol:
    callbacks = ClientCallbacks()
    hm_protocol = None


class _Handshake:
    pubkey = "server-pubkey"


class _Client:
    key = "client-key"
    name = "client"
    crypto_key = "preshared"
    pswd_handshake = None
    handshake = _Handshake()
    binarize = False
    can_escalate = True
    site_id = "site"
    sess = Session(session_id="session")
    sent = None
    disconnected = False

    @property
    def peer(self):
        return f"{self.name}::{self.sess.session_id}"

    def send(self, message):
        if self.sent is None:
            self.sent = []
        self.sent.append(message)

    def disconnect(self):
        self.disconnected = True

    def authorize(self, _message):
        return True


def _protocol(monkeypatch):
    monkeypatch.setattr(
        "hivemind_core.protocol.get_server_config",
        lambda: {"min_protocol_version": 0},
    )
    proto = HiveMindListenerProtocol(
        agent_protocol=_BrokenAgent(),
        binary_data_protocol=_BinaryProtocol(),
        identity=SimpleNamespace(private_key="private", site_id="master-site"),
        db=SimpleNamespace(),
    )
    proto.policy_chain = PolicyChain()
    proto.peer = "master"
    return proto


def test_new_client_handshake_does_not_wait_for_agent_event_bus(monkeypatch):
    proto = _protocol(monkeypatch)
    client = _Client()

    proto.handle_new_client(client)

    assert not client.disconnected
    assert [message.msg_type for message in client.sent] == [
        HiveMessageType.HELLO,
        HiveMessageType.HANDSHAKE,
    ]
    assert proto.agent_protocol.get_bus_called.wait(1)


def test_query_response_does_not_wait_for_agent_event_bus(monkeypatch):
    proto = _protocol(monkeypatch)
    client = _Client()
    inner = HiveMessage(
        HiveMessageType.BUS,
        payload=Message("recognizer_loop:utterance", {"utterances": ["time"]}),
    )
    request = HiveMessage(
        HiveMessageType.QUERY,
        payload=inner,
        metadata={"query_id": "q1", "originator_peer": client.peer},
    )

    proto.handle_query_message(request, client)

    sent_types = [message.msg_type for message in client.sent]
    assert sent_types == [HiveMessageType.QUERY, HiveMessageType.QUERY]
    assert client.sent[0].payload.payload.data["utterance"] == "fast answer"
    assert client.sent[1].payload.payload.msg_type == "hive.query.complete"
    assert proto.agent_protocol.get_bus_called.wait(1)
