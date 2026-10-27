"""A HELLO frame whose wire payload is not a JSON object must never reach
handle_hello_message, and site_id must stay unset.

HIVEMIND-MSG-1 S2 makes HELLO's payload REQUIRED, and S4 makes the empty
object {} its only empty form. hivemind_bus_client>=1.2.3a1 enforces this
at the constructor hivemind-core's own decode() calls
(HiveMessage(**payload), protocol.py:584): a str payload raises
MalformedWirePayload there, before handle_hello_message runs.
"""
import json
import unittest
from unittest.mock import MagicMock

from ovos_bus_client.session import Session

from hivemind_bus_client.message import MalformedWirePayload
from hivemind_core.protocol import HiveMindClientConnection, HiveMindListenerProtocol


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.callbacks = MagicMock()

    db_user = MagicMock()
    db_user.allowed_types = []
    db_user.is_admin = True

    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    return HiveMindListenerProtocol(agent_protocol=agent, db=db)


def _make_client(protocol):
    client = HiveMindClientConnection(
        key="test-key",
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=protocol,
        sess=Session("a-session"),
    )
    client.name = "test-client"
    client.allowed_types = []
    return client


class TestHelloWirePayloadNotObject(unittest.TestCase):
    def test_json_string_hello_payload_is_refused_and_site_id_unset(self):
        protocol = _make_protocol()
        client = _make_client(protocol)
        frame = json.dumps({
            "msg_type": "hello",
            "payload": json.dumps({"site_id": "injected"}),
        })

        with self.assertRaises(MalformedWirePayload):
            client.decode(frame)

        self.assertIsNone(client.sess.site_id)
        self.assertEqual(client.site_id, "unknown")
        rejections = protocol.get_recent_rejections()
        self.assertEqual(len(rejections), 1)
        self.assertEqual(rejections[0]["reason"], "malformed_wire_payload")

    def test_null_hello_payload_is_accepted_with_no_site_id(self):
        protocol = _make_protocol()
        client = _make_client(protocol)
        frame = json.dumps({"msg_type": "hello", "payload": None})

        message = client.decode(frame)
        protocol.handle_message(message, client)

        self.assertIsNone(client.sess.site_id)

    def test_control_empty_object_hello_is_accepted(self):
        protocol = _make_protocol()
        client = _make_client(protocol)
        frame = json.dumps({"msg_type": "hello", "payload": {}})

        message = client.decode(frame)
        protocol.handle_message(message, client)

        self.assertIsNone(client.sess.site_id)
        self.assertEqual(client.send_msg.call_count, 0)


if __name__ == "__main__":
    unittest.main()
