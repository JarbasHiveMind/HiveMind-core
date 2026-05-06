import unittest
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_core.protocol import HiveMindClientConnection, HiveMindListenerProtocol


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.callbacks = MagicMock()

    db_user = MagicMock()
    db_user.skill_blacklist = []
    db_user.intent_blacklist = []
    db_user.message_blacklist = []

    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    return HiveMindListenerProtocol(agent_protocol=agent, db=db)


def _make_client(protocol, pipeline):
    client = HiveMindClientConnection(
        key="test-key",
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=protocol,
    )
    client.name = "test-client"
    client.allowed_types = ["recognizer_loop:utterance"]
    client.sess = Session("session-1", site_id="client-site", pipeline=pipeline)
    return client


class TestSessionPipelineHandling(unittest.TestCase):
    def test_missing_pipeline_is_not_invented_from_core_config(self):
        protocol = _make_protocol()
        client = _make_client(protocol, ["client-pipeline"])
        raw_session = {"session_id": "session-1", "site_id": "client-site"}
        bus_message = Message(
            "recognizer_loop:utterance",
            {"utterances": ["hello"]},
            {"session": raw_session},
        )

        protocol.handle_bus_message(
            HiveMessage(HiveMessageType.BUS, bus_message), client
        )

        emitted = protocol.agent_protocol.bus.emit.call_args[0][0]
        self.assertNotIn("pipeline", emitted.context["session"])
        self.assertEqual(client.sess.pipeline, ["client-pipeline"])

    def test_explicit_pipeline_is_kept(self):
        protocol = _make_protocol()
        client = _make_client(protocol, ["old-pipeline"])
        raw_session = {
            "session_id": "session-1",
            "site_id": "client-site",
            "pipeline": ["client-sent-pipeline"],
        }
        bus_message = Message(
            "recognizer_loop:utterance",
            {"utterances": ["hello"]},
            {"session": raw_session},
        )

        protocol.handle_bus_message(
            HiveMessage(HiveMessageType.BUS, bus_message), client
        )

        emitted = protocol.agent_protocol.bus.emit.call_args[0][0]
        self.assertEqual(
            emitted.context["session"]["pipeline"], ["client-sent-pipeline"]
        )
        self.assertEqual(client.sess.pipeline, ["client-sent-pipeline"])


if __name__ == "__main__":
    unittest.main()
