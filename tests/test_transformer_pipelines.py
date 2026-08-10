"""OVOS transformer pipelines on the hivemind-core text/bus path."""
import unittest
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_core.protocol import HiveMindClientConnection, HiveMindListenerProtocol


class FakeUtteranceService:
    def __init__(self, plugins=("fake",), context_update=None):
        self.plugins = list(plugins)
        self.context_update = context_update or {}

    def transform(self, utterances, context=None):
        context = dict(context or {})
        context.update(self.context_update)
        return [f"corrected:{u}" for u in utterances], context


class FakeMetadataService:
    plugins = ["fake"]

    def transform(self, context=None):
        context = dict(context or {})
        context["metadata_touched"] = True
        return context


class FakeDialogService:
    plugins = ["fake"]

    def transform(self, dialog, context=None):
        return f"rewritten:{dialog}", context or {}


class EmptyService:
    plugins = []


def _make_protocol(**services):
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.get_bus.return_value = agent.bus
    agent.callbacks = MagicMock()

    db_user = MagicMock()
    db_user.skill_blacklist = []
    db_user.intent_blacklist = []
    db_user.message_blacklist = []
    db_user.allowed_types = ["recognizer_loop:utterance"]
    db_user.is_admin = True

    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    services.setdefault("utterance_transformers", EmptyService())
    services.setdefault("metadata_transformers", EmptyService())
    services.setdefault("dialog_transformers", EmptyService())
    return HiveMindListenerProtocol(agent_protocol=agent, db=db, **services)


def _make_client(protocol):
    client = HiveMindClientConnection(
        key="test-key",
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=protocol,
    )
    client.name = "test-client"
    client.allowed_types = ["recognizer_loop:utterance"]
    client.is_admin = True
    client.sess = Session("session-1", site_id="client-site")
    client.send = MagicMock()
    return client


def _utterance_message():
    return Message("recognizer_loop:utterance", {"utterances": ["hello"]}, {})


class TestInjectPathTransformers(unittest.TestCase):
    def test_default_off_passthrough(self):
        protocol = _make_protocol()
        client = _make_client(protocol)
        protocol.handle_inject_agent_msg(_utterance_message(), client)
        emitted = protocol.agent_protocol.bus.emit.call_args[0][0]
        self.assertEqual(emitted.data["utterances"], ["hello"])

    def test_utterances_rewritten_before_agent_bus(self):
        protocol = _make_protocol(utterance_transformers=FakeUtteranceService())
        client = _make_client(protocol)
        protocol.handle_inject_agent_msg(_utterance_message(), client)
        emitted = protocol.agent_protocol.bus.emit.call_args[0][0]
        self.assertEqual(emitted.data["utterances"], ["corrected:hello"])

    def test_metadata_transformers_touch_context(self):
        protocol = _make_protocol(metadata_transformers=FakeMetadataService())
        client = _make_client(protocol)
        protocol.handle_inject_agent_msg(_utterance_message(), client)
        emitted = protocol.agent_protocol.bus.emit.call_args[0][0]
        self.assertTrue(emitted.context["metadata_touched"])

    def test_non_utterance_messages_untouched(self):
        protocol = _make_protocol(utterance_transformers=FakeUtteranceService())
        client = _make_client(protocol)
        client.allowed_types = ["speak"]
        protocol.db.get_client_by_api_key.return_value.allowed_types = ["speak"]
        msg = Message("speak", {"utterance": "hello"}, {})
        protocol.handle_inject_agent_msg(msg, client)
        emitted = protocol.agent_protocol.bus.emit.call_args[0][0]
        self.assertEqual(emitted.data["utterance"], "hello")

    def test_cancellation_terminates_lifecycle(self):
        """A §8.1 cancellation never reaches the agent bus and the client
        receives the §8.2 terminal events (cancelled -> handled)."""
        canceller = FakeUtteranceService(
            context_update={"canceled": True,
                            "cancel_reason": "stop_word",
                            "cancel_by": "fake"})
        protocol = _make_protocol(utterance_transformers=canceller)
        client = _make_client(protocol)
        protocol.handle_inject_agent_msg(_utterance_message(), client)
        protocol.agent_protocol.bus.emit.assert_not_called()
        sent_types = [call.args[0].payload.msg_type
                      for call in client.send.call_args_list]
        self.assertEqual(sent_types,
                         ["ovos.utterance.cancelled", "ovos.utterance.handled"])
        cancelled = client.send.call_args_list[0].args[0].payload
        self.assertEqual(cancelled.data["cancel_reason"], "stop_word")
        self.assertEqual(cancelled.data["cancel_by"], "fake")


class TestQueryPathTransformers(unittest.TestCase):
    def _query_message(self):
        bus_msg = Message("recognizer_loop:utterance",
                          {"utterances": ["hello"], "lang": "en-US"}, {})
        inner = HiveMessage(HiveMessageType.BUS, payload=bus_msg)
        return HiveMessage(HiveMessageType.QUERY, payload=inner)

    def test_dialog_transformers_rewrite_answer_chunks(self):
        protocol = _make_protocol(dialog_transformers=FakeDialogService())
        client = _make_client(protocol)
        protocol.agent_protocol.answer_query.return_value = iter(["the answer"])
        sent = []
        answered = protocol._answer_query_locally(
            self._query_message(), client, "qid", client.peer,
            HiveMessageType.QUERY, None, sent.append)
        self.assertTrue(answered)
        speak = sent[0].payload.payload
        self.assertEqual(speak.data["utterance"], "rewritten:the answer")

    def test_utterance_transformers_rewrite_query(self):
        protocol = _make_protocol(utterance_transformers=FakeUtteranceService())
        client = _make_client(protocol)
        protocol.agent_protocol.answer_query.return_value = iter(["ok"])
        protocol._answer_query_locally(
            self._query_message(), client, "qid", client.peer,
            HiveMessageType.QUERY, None, MagicMock())
        args, kwargs = protocol.agent_protocol.answer_query.call_args
        self.assertEqual(args[0], "corrected:hello")

    def test_canceled_query_declines(self):
        canceller = FakeUtteranceService(
            context_update={"canceled": True, "cancel_reason": "policy_block"})
        protocol = _make_protocol(utterance_transformers=canceller)
        client = _make_client(protocol)
        answered = protocol._answer_query_locally(
            self._query_message(), client, "qid", client.peer,
            HiveMessageType.QUERY, None, MagicMock())
        self.assertFalse(answered)
        protocol.agent_protocol.answer_query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
