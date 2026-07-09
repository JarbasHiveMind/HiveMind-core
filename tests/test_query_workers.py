import threading
import time
from types import SimpleNamespace

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivemind_core.policy import PolicyChain
from hivemind_core.protocol import HiveMindListenerProtocol
from hivemind_plugin_manager.protocols import ClientCallbacks
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session


class _Bus:
    def __init__(self):
        self.messages = []

    def emit(self, message):
        self.messages.append(message)


class _Agent:
    callbacks = ClientCallbacks()

    def __init__(self, delay=0.05):
        self.bus = _Bus()
        self.delay = delay
        self.started = []
        self.lock = threading.Lock()
        self.hm_protocol = None

    def get_bus(self, _client=None):
        return self.bus

    def answer_query(self, utterance, _lang, client=None):
        with self.lock:
            self.started.append((utterance, time.monotonic()))
        time.sleep(self.delay)
        yield f"answer {utterance}"


class _BlockingAgent(_Agent):
    def __init__(self):
        super().__init__(delay=0)
        self.started_event = threading.Event()
        self.release_event = threading.Event()

    def answer_query(self, utterance, _lang, client=None):
        self.started_event.set()
        self.release_event.wait(1)
        yield f"answer {utterance}"


class _BinaryProtocol:
    callbacks = ClientCallbacks()
    hm_protocol = None


class _Client:
    key = "client-key"
    crypto_key = "preshared"
    pswd_handshake = None
    binarize = False
    can_escalate = True
    site_id = "site"
    sent = None
    disconnected = False

    def __init__(self, name="client"):
        self.name = name
        self.sess = Session(session_id=f"{name}-session")

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


def _protocol(monkeypatch, agent=None):
    monkeypatch.setattr(
        "hivemind_core.protocol.get_server_config",
        lambda: {"min_protocol_version": 0},
    )
    proto = HiveMindListenerProtocol(
        agent_protocol=agent or _Agent(),
        binary_data_protocol=_BinaryProtocol(),
        identity=SimpleNamespace(private_key="private", site_id="master-site"),
        db=SimpleNamespace(),
    )
    proto.policy_chain = PolicyChain()
    proto.peer = "master"
    return proto


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


def _wait_for_messages(client, count, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.sent is not None and len(client.sent) >= count:
            return client.sent
        time.sleep(0.01)
    return client.sent or []


def test_query_requests_run_concurrently(monkeypatch):
    agent = _Agent(delay=0.15)
    proto = _protocol(monkeypatch, agent=agent)
    client1 = _Client()
    client2 = _Client(name="client2")

    proto.handle_query_message(_request("q1", "one"), client1)
    proto.handle_query_message(_request("q2", "two"), client2)

    assert len(_wait_for_messages(client1, 2)) == 2
    assert len(_wait_for_messages(client2, 2)) == 2
    assert len(agent.started) == 2
    start_times = [started_at for _, started_at in agent.started]
    assert max(start_times) - min(start_times) < agent.delay


def test_query_worker_pool_returns_busy_when_saturated(monkeypatch):
    agent = _BlockingAgent()
    proto = _protocol(monkeypatch, agent=agent)
    proto.query_workers = 1
    proto.query_queue_size = 0
    client1 = _Client()
    client2 = _Client(name="client2")

    proto.handle_query_message(_request("q1", "one"), client1)
    assert agent.started_event.wait(1)

    proto.handle_query_message(_request("q2", "two"), client2)

    sent = _wait_for_messages(client2, 1)
    assert len(sent) == 1
    assert sent[0].payload.payload.data["error"] == "busy"
    agent.release_event.set()
    assert len(_wait_for_messages(client1, 2)) == 2
