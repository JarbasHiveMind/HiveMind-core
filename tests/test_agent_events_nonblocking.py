"""Lifecycle telemetry must not block client handshakes or direct queries."""

import threading
import time
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


class _SlowAgent(_BrokenAgent):
    def __init__(self, delay=0.2):
        super().__init__()
        self.delay = delay
        self.started = []
        self.lock = threading.Lock()

    def answer_query(self, utterance, _lang, client=None):
        with self.lock:
            self.started.append((utterance, time.monotonic()))
        time.sleep(self.delay)
        yield f"answer {utterance}"


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


def _wait_for_messages(client, count, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.sent is not None and len(client.sent) >= count:
            return client.sent
        time.sleep(0.01)
    return client.sent or []


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

    sent = _wait_for_messages(client, 2)
    sent_types = [message.msg_type for message in sent]
    assert sent_types == [HiveMessageType.QUERY, HiveMessageType.QUERY]
    assert sent[0].payload.payload.data["utterance"] == "fast answer"
    assert sent[1].payload.payload.msg_type == "hive.query.complete"
    assert proto.agent_protocol.get_bus_called.wait(1)


def test_disconnect_prunes_connection_scoped_state(monkeypatch):
    proto = _protocol(monkeypatch)
    client = _Client()
    proto.clients[client.peer] = client
    proto._last_seen_next_flush[client.key] = 123.0
    proto.trusted_pubkeys[client.key] = "pinned-key"

    proto.handle_client_disconnected(client)

    assert client.disconnected
    assert client.peer not in proto.clients
    assert client.key not in proto._last_seen_next_flush
    assert client.key not in proto.trusted_pubkeys


def test_query_requests_run_concurrently(monkeypatch):
    proto = _protocol(monkeypatch)
    proto.agent_protocol = _SlowAgent(delay=0.2)
    proto.agent_protocol.hm_protocol = proto
    proto._query_workers_started = False
    proto._start_query_workers()
    client1 = _Client()
    client2 = _Client()
    client2.name = "client2"

    def _request(query_id, text):
        inner = HiveMessage(
            HiveMessageType.BUS,
            payload=Message("recognizer_loop:utterance", {"utterances": [text]}),
        )
        return HiveMessage(
            HiveMessageType.QUERY,
            payload=inner,
            metadata={"query_id": query_id},
        )

    proto.handle_query_message(_request("q1", "one"), client1)
    proto.handle_query_message(_request("q2", "two"), client2)

    assert len(_wait_for_messages(client1, 2, timeout=1.0)) == 2
    assert len(_wait_for_messages(client2, 2, timeout=1.0)) == 2
    assert len(proto.agent_protocol.started) == 2
    start_times = [started_at for _, started_at in proto.agent_protocol.started]
    assert max(start_times) - min(start_times) < proto.agent_protocol.delay


def test_query_workers_can_be_tuned_from_env(monkeypatch):
    monkeypatch.setattr(
        "hivemind_core.protocol.get_server_config",
        lambda: {"min_protocol_version": 0},
    )
    monkeypatch.setenv("HIVEMIND_QUERY_WORKERS", "64")
    monkeypatch.setenv("HIVEMIND_QUERY_QUEUE_SIZE", "512")

    assert HiveMindListenerProtocol._query_worker_count() == 64
    assert HiveMindListenerProtocol._query_queue_size() == 512


def test_configured_query_workers_win_over_env(monkeypatch):
    monkeypatch.setattr(
        "hivemind_core.protocol.get_server_config",
        lambda: {
            "min_protocol_version": 0,
            "query_workers": 12,
            "query_queue_size": 24,
        },
    )
    monkeypatch.setenv("HIVEMIND_QUERY_WORKERS", "64")
    monkeypatch.setenv("HIVEMIND_QUERY_QUEUE_SIZE", "512")

    assert HiveMindListenerProtocol._query_worker_count() == 12
    assert HiveMindListenerProtocol._query_queue_size() == 24
