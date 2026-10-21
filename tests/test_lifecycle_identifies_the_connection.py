"""A lifecycle event names the connection, not only the client.

``key`` is the access key: it names a CLIENT row, and it is not a secret —
``list-clients`` prints it and the admin panel shows it. What it cannot do is
tell two connections apart, because two satellites may hold the same access
key. ``peer`` is unique per connection.

Both are on the payload. Removing ``key`` would break a consumer that reads
the documented field for no gain; carrying only ``key`` leaves two
disconnects on one shared key indistinguishable. ``peer`` does not pair a
disconnect with its connect: the connect fires before HELLO, and HELLO
replaces the session the peer string is built from.
"""
import unittest
from unittest.mock import MagicMock, patch

from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)

SHARED_KEY = "one-key-two-satellites"


def _protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.callbacks = MagicMock()
    return HiveMindListenerProtocol(agent_protocol=agent, db=MagicMock())


def _client(proto, peer):
    client = HiveMindClientConnection(
        key=SHARED_KEY, send_msg=MagicMock(), disconnect=MagicMock(),
        hm_protocol=proto)
    client.name = peer
    return client


class TestLifecyclePayloads(unittest.TestCase):

    def _emitted(self, proto, fn, client):
        sent = []
        with patch.object(proto, "_emit_lifecycle",
                          side_effect=lambda c, m: sent.append(m)):
            fn(client)
        return sent

    def test_disconnect_carries_both_identifiers(self):
        proto = _protocol()
        client = _client(proto, "sat-a::1::kitchen::s1")
        sent = self._emitted(proto, proto.handle_client_disconnected, client)
        self.assertTrue(sent, "no lifecycle message was emitted")
        data = sent[0].data
        self.assertEqual(data.get("key"), SHARED_KEY)
        self.assertEqual(data.get("peer"), client.peer)

    def test_two_connections_on_one_key_are_distinguishable(self):
        """The whole point: same key, different peer."""
        proto = _protocol()
        a = _client(proto, "sat-a::1::kitchen::s1")
        b = _client(proto, "sat-b::1::kitchen::s2")

        first = self._emitted(proto, proto.handle_client_disconnected, a)[0].data
        second = self._emitted(proto, proto.handle_client_disconnected, b)[0].data

        self.assertEqual(first["key"], second["key"])
        self.assertNotEqual(first["peer"], second["peer"],
                            "two connections sharing a key are indistinguishable")

    def test_the_documented_key_field_is_not_removed(self):
        """`key` is documented in docs/protocol.md; consumers read it."""
        proto = _protocol()
        client = _client(proto, "sat-a::1::kitchen::s1")
        data = self._emitted(proto, proto.handle_client_disconnected, client)[0].data
        self.assertIn("key", data)


if __name__ == "__main__":
    unittest.main()
