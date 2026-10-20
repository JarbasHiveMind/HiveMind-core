"""The hub treats the utterance entry topic ``ovos.utterance.handle``
(OVOS-PIPELINE-1 §9.1) exactly like the legacy ``recognizer_loop:utterance``:
transformers run, a cancellation is honoured, QUERY extraction works, and the
``add-client`` hint names both."""
import pytest
from click.testing import CliRunner
from ovos_bus_client.message import Message

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_core.scripts import add_client
from tests.test_transformer_pipelines import (FakeMetadataService,
                                              FakeUtteranceService,
                                              _make_client, _make_protocol)

TOPICS = ["ovos.utterance.handle", "recognizer_loop:utterance"]


def _inject(protocol, topic):
    client = _make_client(protocol)
    client.allowed_types = [topic]
    protocol.db.get_client_by_api_key.return_value.allowed_types = [topic]
    protocol.handle_inject_agent_msg(
        Message(topic, {"utterances": ["hello"]}, {}), client)
    return client


@pytest.mark.parametrize("topic", TOPICS)
def test_utterance_transformers_run_and_topic_is_kept(topic):
    protocol = _make_protocol(utterance_transformers=FakeUtteranceService(),
                              metadata_transformers=FakeMetadataService())
    _inject(protocol, topic)
    emitted = protocol.agent_protocol.bus.emit.call_args[0][0]
    assert emitted.msg_type == topic
    assert emitted.data["utterances"] == ["corrected:hello"]
    assert emitted.context["metadata_touched"] is True


@pytest.mark.parametrize("topic", TOPICS)
def test_cancellation_is_honoured(topic):
    canceller = FakeUtteranceService(context_update={
        "canceled": True, "cancel_reason": "stop_word", "cancel_by": "fake"})
    protocol = _make_protocol(utterance_transformers=canceller)
    client = _inject(protocol, topic)
    protocol.agent_protocol.bus.emit.assert_not_called()
    sent = [c.args[0].payload.msg_type for c in client.send.call_args_list]
    assert sent == ["ovos.utterance.cancelled", "ovos.utterance.handled"]


@pytest.mark.parametrize("topic", TOPICS)
def test_query_extraction_accepts_the_topic(topic):
    protocol = _make_protocol(utterance_transformers=FakeUtteranceService())
    client = _make_client(protocol)
    client.allowed_types = [topic]
    protocol.db.get_client_by_api_key.return_value.allowed_types = [topic]
    protocol.agent_protocol.answer_query.return_value = iter(["ok"])
    inner = HiveMessage(HiveMessageType.BUS, payload=Message(
        topic, {"utterances": ["hello"], "lang": "en-US"}, {}))
    sent = []
    answered = protocol._answer_query_locally(
        HiveMessage(HiveMessageType.QUERY, payload=inner), client, "qid",
        client.peer, HiveMessageType.QUERY, None, sent.append)
    assert answered
    assert protocol.agent_protocol.answer_query.call_args.args[0] == "corrected:hello"


def test_query_still_refuses_other_topics():
    protocol = _make_protocol()
    client = _make_client(protocol)
    inner = HiveMessage(HiveMessageType.BUS, payload=Message(
        "ovos.utterance.handled", {"utterances": ["hello"]}, {}))
    assert not protocol._answer_query_locally(
        HiveMessage(HiveMessageType.QUERY, payload=inner), client, "qid",
        client.peer, HiveMessageType.QUERY, None, lambda m: None)
    protocol.agent_protocol.answer_query.assert_not_called()


def test_add_client_hint_names_both_topics(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    result = CliRunner().invoke(add_client, [
        "--access-key", "key-topics",
        "--password", "upright collar icefall sixpaned",
        "--allow-weak-password"])
    assert result.exit_code == 0, result.output
    hint = result.output.split("Grant access explicitly", 1)[1]
    assert "ovos.utterance.handle" in hint
    assert "recognizer_loop:utterance" in hint
