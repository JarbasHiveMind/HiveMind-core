import unittest
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_bus_client.message import HiveMindBinaryPayloadType
from hivemind_core.protocol import HiveMindClientConnection, HiveMindListenerProtocol

try:
    from hivemind_plugin_manager.protocols import PolicyDecision, PolicyProtocol
except ImportError:
    PolicyDecision = None
    PolicyProtocol = object


class CapturePolicy(PolicyProtocol):
    def __init__(self, bus_decision=None):
        super().__init__()
        self.bus_decision = bus_decision or PolicyDecision()
        self.contexts = []
        self.recorded = []

    def authorize_hive_message(self, message, context):
        self.contexts.append(context)
        return PolicyDecision()

    def authorize_bus_message(self, message, context):
        self.contexts.append(context)
        return self.bus_decision

    def record_bus_message(self, message, context, result=None):
        self.recorded.append((message, context, result))


def _make_protocol(policy_protocols=None):
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.callbacks = MagicMock()

    db_user = MagicMock()
    db_user.skill_blacklist = []
    db_user.intent_blacklist = []
    db_user.message_blacklist = []
    db_user.api_key = "test-key"
    db_user.name = "server-user"

    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    return HiveMindListenerProtocol(
        agent_protocol=agent,
        db=db,
        policy_protocols=policy_protocols or [],
    )


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

    def test_explicit_none_pipeline_is_kept(self):
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
        self.assertIsNone(emitted.context["session"]["pipeline"])
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

    def test_no_policy_skips_hive_message_policy_user_lookup(self):
        protocol = _make_protocol()
        client = _make_client(protocol, ["client-pipeline"])
        raw_session = {"session_id": "session-1", "site_id": "client-site"}
        bus_message = _make_bus_message({"session": raw_session})

        protocol.handle_message(
            HiveMessage(HiveMessageType.BUS, bus_message), client
        )

        # One lookup updates blacklist data and one updates last_seen.
        # Policy pre-authorization must not add a third lookup when disabled.
        self.assertEqual(protocol.db.get_client_by_api_key.call_count, 2)

    def test_no_policy_skips_binary_policy_user_lookup(self):
        protocol = _make_protocol()
        client = _make_client(protocol, ["client-pipeline"])
        binary_message = HiveMessage(
            HiveMessageType.BINARY,
            b"audio",
            bin_type=HiveMindBinaryPayloadType.RAW_AUDIO,
            metadata={},
        )

        protocol.handle_binary_message(binary_message, client)

        protocol.db.get_client_by_api_key.assert_not_called()

    @unittest.skipIf(PolicyDecision is None, "policy protocol support is not installed")
    def test_policy_context_patch_updates_session_acl(self):
        policy = CapturePolicy(PolicyDecision(
            context_patch={
                "session": {
                    "blacklisted_intents": ["quota.intent"],
                    "blacklisted_skills": ["quota.skill"],
                }
            }
        ))
        protocol = _make_protocol([policy])
        client = _make_client(protocol, ["client-pipeline"])
        client.send = MagicMock()
        raw_session = {"session_id": "session-1", "site_id": "client-site"}
        bus_message = _make_bus_message({"session": raw_session})

        protocol.handle_bus_message(
            HiveMessage(HiveMessageType.BUS, bus_message), client
        )

        emitted = protocol.agent_protocol.bus.emit.call_args[0][0]
        self.assertIn("quota.intent", emitted.context["session"]["blacklisted_intents"])
        self.assertIn("quota.skill", emitted.context["session"]["blacklisted_skills"])
        self.assertEqual(len(policy.recorded), 1)

    @unittest.skipIf(PolicyDecision is None, "policy protocol support is not installed")
    def test_policy_denial_blocks_bus_emit_and_notifies_client(self):
        policy = CapturePolicy(PolicyDecision(
            allowed=False,
            reason="quota exceeded",
            code="quota_exceeded",
            data={"period": "daily"},
        ))
        protocol = _make_protocol([policy])
        client = _make_client(protocol, ["client-pipeline"])
        client.send = MagicMock()
        raw_session = {"session_id": "session-1", "site_id": "client-site"}
        bus_message = _make_bus_message({"session": raw_session})

        protocol.handle_bus_message(
            HiveMessage(HiveMessageType.BUS, bus_message), client
        )

        protocol.agent_protocol.bus.emit.assert_not_called()
        response = client.send.call_args[0][0]
        self.assertEqual(response.msg_type, HiveMessageType.BUS)
        self.assertEqual(response.payload.msg_type, "hive.policy.denied")
        self.assertEqual(response.payload.data["code"], "quota_exceeded")
        self.assertEqual(response.payload.data["reason"], "quota exceeded")

    @unittest.skipIf(PolicyDecision is None, "policy protocol support is not installed")
    def test_policy_context_uses_server_owned_user(self):
        policy = CapturePolicy()
        protocol = _make_protocol([policy])
        client = _make_client(protocol, ["client-pipeline"])
        raw_session = {"session_id": "session-1", "site_id": "client-site"}
        bus_message = _make_bus_message({
            "session": raw_session,
            "api_key": "client-controlled",
            "name": "client-controlled",
        })

        protocol.handle_bus_message(
            HiveMessage(HiveMessageType.BUS, bus_message), client
        )

        self.assertTrue(policy.contexts)
        self.assertEqual(policy.contexts[-1].client.key, "test-key")
        self.assertEqual(policy.contexts[-1].user.api_key, "test-key")
        self.assertEqual(policy.contexts[-1].user.name, "server-user")


if __name__ == "__main__":
    unittest.main()
