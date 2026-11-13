"""A QUERY or CASCADE is answered off the IOLoop.

The answering backend streams its chunks from a blocking generator that waits
as long as a skill takes to speak. HIVEMIND-AGENT-1 §4.1 requires each chunk to
reach the originator as it is produced, and the one IOLoop thread serves every
connected client, so iterating that generator on the loop thread froze every
other client until the stream ended.
"""
import asyncio
import dataclasses
import os
import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_plugin_manager.transformer_services import (
    DialogTransformersService, MetadataTransformersService,
    UtteranceTransformersService)
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import (QUERY_STREAM_END, HiveMindListenerProtocol,
                                    _DaemonWorkerPool)

NODE_KEY = "pubkey-of-this-node"


def _make_node(answer_query) -> HiveMindListenerProtocol:
    node = object.__new__(HiveMindListenerProtocol)
    node.peer = "master:0.0.0.0"
    node.identity = MagicMock(public_key=NODE_KEY, site_id=None)
    node.clients = {}
    node.default_lang = "en-US"
    node.agent_protocol = MagicMock()
    node.agent_protocol.answer_query = answer_query
    node.utterance_transformers = UtteranceTransformersService(config={})
    node.metadata_transformers = MetadataTransformersService(config={})
    node.dialog_transformers = DialogTransformersService(config={})
    node._upstream_hm = None
    node._unpack_message = MagicMock(
        return_value=Message("recognizer_loop:utterance", {"utterances": ["hi"]}))
    node.get_bus = MagicMock(return_value=MagicMock())
    node._admit_for_query = lambda message, client: message
    node._record_outstanding_query = MagicMock()
    return node


def _client():
    client = MagicMock()
    client.peer = "asker::1"
    client.can_escalate = True
    client.can_propagate = True
    client.sent = []
    client.send = lambda m, *a: client.sent.append(m)
    return client


def _query(msg_type=HiveMessageType.QUERY):
    inner = HiveMessage(HiveMessageType.BUS,
                        payload=Message("recognizer_loop:utterance",
                                        {"utterances": ["hi"]}))
    return HiveMessage(msg_type, payload=inner,
                       metadata={"query_id": "q1", "originator_peer": "asker::1"})


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _slow_agent(release: threading.Event, started: threading.Event):
    def answer_query(utterance, lang, client=None):
        yield "first chunk"
        started.set()
        release.wait(10)
        yield "second chunk"
    return answer_query


def test_slow_query_does_not_hold_the_loop_for_other_clients():
    release, started = threading.Event(), threading.Event()
    node = _make_node(_slow_agent(release, started))
    asker = _client()
    seen = {}

    async def scenario():
        loop = asyncio.get_running_loop()
        # the transport dispatches each frame as a loop callback
        loop.call_soon(node.handle_query_message, _query(), asker)
        loop.call_soon(lambda: seen.setdefault("other_client_at", time.monotonic()))
        await asyncio.sleep(0.2)
        seen["agent_still_blocked"] = not release.is_set()
        release.set()

    t0 = time.monotonic()
    try:
        asyncio.run(scenario())
        assert seen["agent_still_blocked"]
        assert seen["other_client_at"] - t0 < 1.0, \
            "a second client's frame waited for the QUERY's answer stream"
        assert _wait_for(lambda: len(asker.sent) == 3)
    finally:
        release.set()


def test_chunks_are_relayed_as_produced_in_order_then_stream_end():
    release, started = threading.Event(), threading.Event()
    node = _make_node(_slow_agent(release, started))
    asker = _client()
    try:
        node.handle_query_message(_query(), asker)
        assert started.wait(5)
        assert _wait_for(lambda: len(asker.sent) == 1)
        first = asker.sent[0].payload.payload
        assert first.msg_type == "speak"
        assert first.data["utterance"] == "first chunk", \
            "the first chunk must reach the asker while the agent is still working"
        release.set()
        assert _wait_for(lambda: len(asker.sent) == 3)
    finally:
        release.set()
    types = [m.payload.payload.msg_type for m in asker.sent]
    texts = [m.payload.payload.data.get("utterance") for m in asker.sent]
    assert types == ["speak", "speak", QUERY_STREAM_END]
    assert texts[:2] == ["first chunk", "second chunk"]


def test_declined_query_escalates_upstream_after_the_agent_returns():
    release = threading.Event()

    def declining(utterance, lang, client=None):
        release.wait(10)
        return iter(())

    node = _make_node(declining)
    node._upstream_hm = MagicMock()
    escalated = []
    node.query_to_master = escalated.append
    node._rewrap = MagicMock(return_value=_query())
    asker = _client()
    try:
        node.handle_query_message(_query(), asker)
        assert escalated == [], "escalated before the agent had answered or declined"
        release.set()
        assert _wait_for(lambda: len(escalated) == 1)
    finally:
        release.set()
    assert asker.sent == [], "a decline is wire-invisible to the originator"


def test_declined_query_at_the_top_answers_no_answer():
    node = _make_node(lambda utterance, lang, client=None: iter(()))
    asker = _client()
    node.handle_query_message(_query(), asker)
    assert _wait_for(lambda: len(asker.sent) == 1)
    error = asker.sent[0].payload.payload
    assert error.msg_type == "hive.query.timeout"
    assert error.data == {"query_id": "q1", "error": "no_answer"}


def test_cascade_is_forwarded_without_waiting_for_the_local_answer():
    release, started = threading.Event(), threading.Event()
    node = _make_node(_slow_agent(release, started))
    node._route_query_response = MagicMock()
    node._is_routing_loop = MagicMock(return_value=False)
    node._append_self_hop = MagicMock()
    node._rewrap = MagicMock(return_value=_query(HiveMessageType.CASCADE))
    forwarded = []
    node.cascade_to_master = forwarded.append
    try:
        t0 = time.monotonic()
        node.handle_cascade_message(_query(HiveMessageType.CASCADE), _client())
        assert time.monotonic() - t0 < 1.0, \
            "the CASCADE handler waited for the local agent"
        assert forwarded, "the CASCADE was not fanned out to the other peers"
        assert not release.is_set()
        release.set()
        assert _wait_for(lambda: node._route_query_response.call_count == 3)
    finally:
        release.set()


def test_queries_over_the_limit_count_as_declined():
    release = threading.Event()
    node = _make_node(lambda utterance, lang, client=None: (
        release.wait(10), iter(()))[1])
    node.QUERY_MAX_IN_FLIGHT = 2
    escalated = []
    node._upstream_hm = MagicMock()
    node.query_to_master = escalated.append
    node._rewrap = MagicMock(return_value=_query())
    try:
        for _ in range(3):
            node.handle_query_message(_query(), _client())
        assert len(escalated) == 1, "the query over the limit must be declined at once"
    finally:
        release.set()
    assert _wait_for(lambda: len(escalated) == 3)
    assert _wait_for(lambda: node._query_in_flight == 0)


def test_query_executor_is_not_a_dataclass_field():
    names = {f.name for f in dataclasses.fields(HiveMindListenerProtocol)}
    assert "_query_executor" not in names


def test_a_query_after_shutdown_is_answered_by_a_new_pool():
    node = _make_node(lambda utterance, lang, client=None: iter(["still here"]))
    before = _client()
    node.handle_query_message(_query(), before)
    assert _wait_for(lambda: len(before.sent) == 2)
    node.shutdown()
    asker = _client()
    node.handle_query_message(_query(), asker)
    assert _wait_for(lambda: len(asker.sent) == 2)
    types = [m.payload.payload.msg_type for m in asker.sent]
    assert types == ["speak", QUERY_STREAM_END]
    assert asker.sent[0].payload.payload.data["utterance"] == "still here"
    assert _wait_for(lambda: node._query_in_flight == 0)


def test_shutdown_drops_queued_answers_and_frees_their_slots():
    release = threading.Event()
    ran = []

    def answer_query(utterance, lang, client=None):
        ran.append(1)
        release.wait(10)
        return iter(())

    node = _make_node(answer_query)
    node.QUERY_WORKERS = 1
    try:
        for _ in range(3):
            node.handle_query_message(_query(), _client())
        assert _wait_for(lambda: len(ran) == 1)
        node.shutdown()
        assert node._query_in_flight == 0
        release.set()
        time.sleep(0.3)
        assert len(ran) == 1, "a queued answer ran after shutdown"
        assert node._query_in_flight == 0
    finally:
        release.set()


def test_shutdown_releases_the_threads_waiting_for_a_stuck_pool():
    forever = threading.Event()

    def stuck(utterance, lang, client=None):
        yield "partial"
        forever.wait(30)

    node = _make_node(stuck)
    node.QUERY_WORKERS = 2
    before = set(threading.enumerate())

    def query_threads():
        return [t for t in threading.enumerate()
                if t not in before and t.name == "hm-query" and t.is_alive()]

    try:
        for _ in range(10):
            node.handle_query_message(_query(), _client())
        assert _wait_for(lambda: len(query_threads()) == 10)
        node.shutdown()
        # the 2 holders never finish; the 8 waiters must not wait for them
        assert _wait_for(lambda: len(query_threads()) == 2, timeout=3.0), \
            f"{len(query_threads())} threads still wait on the closed pool"
    finally:
        forever.set()


def test_queued_jobs_start_in_arrival_order():
    pool = _DaemonWorkerPool(1, "hm-order")
    started = []
    count = 20

    def job(index):
        def run():
            started.append(index)
            time.sleep(0.05)
        return run

    for index in range(count):
        pool.submit(job(index))
        time.sleep(0.01)
    assert _wait_for(lambda: len(started) == count, timeout=10.0)
    assert started == list(range(count))


_STUCK_BACKEND_SCRIPT = """
import sys, threading, time
sys.path.insert(0, sys.argv[1])
from test_query_off_loop import _make_node, _client, _query

forever = threading.Event()

def stuck(utterance, lang, client=None):
    yield "partial"
    forever.wait()

node = _make_node(stuck)
asker = _client()
node.handle_query_message(_query(), asker)
while not asker.sent:
    pass
t0 = time.monotonic()
node.shutdown()
print("%.3f" % (time.monotonic() - t0), flush=True)
"""


def test_a_stuck_answer_stream_does_not_hold_the_process_open():
    tests_dir = os.path.dirname(os.path.abspath(__file__))
    result = subprocess.run(
        [sys.executable, "-c", _STUCK_BACKEND_SCRIPT, tests_dir],
        capture_output=True, text=True, timeout=15,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)})
    assert result.returncode == 0, result.stderr
    assert float(result.stdout.splitlines()[-1]) < 1.0


def test_denied_query_is_not_escalated_even_when_the_pool_is_full():
    node = _make_node(lambda utterance, lang, client=None: iter(()))
    node._admit_for_query = lambda message, client: None
    node.QUERY_MAX_IN_FLIGHT = 0
    node._upstream_hm = MagicMock()
    node.query_to_master = MagicMock()
    node.handle_query_message(_query(), _client())
    node.query_to_master.assert_not_called()


def test_denied_cascade_is_not_forwarded():
    node = _make_node(lambda utterance, lang, client=None: iter(()))
    node._admit_for_query = lambda message, client: None
    node.cascade_to_master = MagicMock()
    peer = MagicMock(peer="other::2")
    node.clients = {"other::2": peer}
    node.handle_cascade_message(_query(HiveMessageType.CASCADE), _client())
    node.cascade_to_master.assert_not_called()
    peer.send.assert_not_called()


def test_query_with_a_non_utterance_inner_message_is_forwarded_not_raised():
    node = _make_node(lambda utterance, lang, client=None: iter(()))
    node._upstream_hm = MagicMock()
    escalated = []
    node.query_to_master = escalated.append
    node._rewrap = MagicMock(return_value=_query())
    speak = HiveMessage(HiveMessageType.QUERY, payload=HiveMessage(
        HiveMessageType.BUS, payload=Message("speak", {"utterance": "hi"})),
        metadata={"query_id": "q1", "originator_peer": "asker::1"})
    node.handle_query_message(speak, _client())
    assert _wait_for(lambda: len(escalated) == 1)
