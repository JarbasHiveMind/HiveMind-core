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
    db_user.allowed_types = ["recognizer_loop:utterance"]
    db_user.is_admin = True

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
    # These tests target session-pipeline plumbing, not admission ACL.
    # Marked admin so OVOSAgentPolicy lets ``session_id == "default"``
    # payloads through (the only check it gates on is_admin).
    # MessageTypeACLPolicy ignores is_admin — allowed_types is set explicitly
    # above to cover its whitelist check.
    client.is_admin = True
    client.sess = Session("session-1", site_id="client-site", pipeline=pipeline)
    return client


def _make_bus_message(context):
    return Message(
        "recognizer_loop:utterance",
        {"utterances": ["hello"]},
        context,
    )


class TestSessionPipelineHandling(unittest.TestCase):
    def test_missing_pipeline_is_not_invented_from_core_config(self):
        protocol = _make_protocol()
        client = _make_client(protocol, ["client-pipeline"])
        raw_session = {"session_id": "session-1", "site_id": "client-site"}
        bus_message = _make_bus_message({"session": raw_session})

        protocol.handle_bus_message(
            HiveMessage(HiveMessageType.BUS, bus_message), client
        )

        emitted = protocol.agent_protocol.bus.emit.call_args[0][0]
        self.assertNotIn("pipeline", emitted.context["session"])
        self.assertEqual(client.sess.pipeline, ["client-pipeline"])

    def test_missing_session_key_is_not_given_pipeline(self):
        protocol = _make_protocol()
        client = _make_client(protocol, ["client-pipeline"])
        client.is_admin = True
        bus_message = _make_bus_message({})

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
        bus_message = _make_bus_message({"session": raw_session})

        protocol.handle_bus_message(
            HiveMessage(HiveMessageType.BUS, bus_message), client
        )

        emitted = protocol.agent_protocol.bus.emit.call_args[0][0]
        self.assertEqual(
            emitted.context["session"]["pipeline"], ["client-sent-pipeline"]
        )
        self.assertEqual(client.sess.pipeline, ["client-sent-pipeline"])

    def test_explicit_none_pipeline_is_treated_as_absent(self):
        # OVOS-SESSION-1 §2: a null field is treated as omitted; the bridge
        # strips it rather than forwarding an explicit null.
        protocol = _make_protocol()
        client = _make_client(protocol, ["old-pipeline"])
        raw_session = {
            "session_id": "session-1",
            "site_id": "client-site",
            "pipeline": None,
        }
        bus_message = _make_bus_message({"session": raw_session})

        protocol.handle_bus_message(
            HiveMessage(HiveMessageType.BUS, bus_message), client
        )

        emitted = protocol.agent_protocol.bus.emit.call_args[0][0]
        self.assertNotIn("pipeline", emitted.context["session"])
        self.assertIsNone(client.sess.pipeline)

    def test_invalid_bus_payload_is_ignored(self):
        protocol = _make_protocol()
        client = _make_client(protocol, ["client-pipeline"])

        protocol.handle_bus_message(
            HiveMessage(HiveMessageType.BUS, {"context": {}}), client
        )

        protocol.agent_protocol.bus.emit.assert_not_called()
        client.disconnect.assert_not_called()
        self.assertEqual(client.sess.pipeline, ["client-pipeline"])

    def test_agent_bus_callback_runs_once(self):
        protocol = _make_protocol()
        protocol.agent_bus_callback = MagicMock()
        client = _make_client(protocol, ["client-pipeline"])
        raw_session = {"session_id": "session-1", "site_id": "client-site"}
        bus_message = _make_bus_message({"session": raw_session})

        protocol.handle_bus_message(
            HiveMessage(HiveMessageType.BUS, bus_message), client
        )

        protocol.agent_bus_callback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
