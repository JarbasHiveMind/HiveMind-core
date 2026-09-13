"""Rejected connections are kept in a bounded ring for the node's operator.

Each rejection path records its close code and reason on
``HiveMindListenerProtocol.recent_rejections``. The ring holds no access key
or password, and nothing from it is sent to the rejected client beyond the
close frame the path already sends.
"""
import time
import unittest
from unittest.mock import MagicMock, patch

from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.callbacks = MagicMock()
    db = MagicMock()
    return HiveMindListenerProtocol(agent_protocol=agent, db=db)


def _make_client(protocol, **kwargs):
    client = HiveMindClientConnection(
        key="secret-access-key", send_msg=MagicMock(), disconnect=MagicMock(),
        hm_protocol=protocol, **kwargs)
    client.name = "test-client"
    return client


class TestRecentRejections(unittest.TestCase):

    def test_sub_v3_rejection_recorded_with_reason(self):
        proto = _make_protocol()
        client = _make_client(proto, pswd_handshake=None)
        with patch("hivemind_core.protocol.NOISE_SUPPORTED", True):
            proto.handle_new_client(client)
        entries = proto.get_recent_rejections()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["code"], 1008)
        self.assertEqual(entry["reason"], client.disconnect.call_args.args[1])
        self.assertEqual(entry["peer"], client.peer)
        self.assertEqual(set(entry), {"time", "peer", "code", "reason"})

    def test_invalid_key_recorded_once(self):
        proto = _make_protocol()
        client = _make_client(proto)
        proto.handle_invalid_key_connected(client)
        proto.handle_invalid_key_connected(client)
        entries = proto.get_recent_rejections()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["reason"], "invalid access key or password")

    def test_noise_abort_keeps_specific_reason(self):
        proto = _make_protocol()
        client = _make_client(proto)
        proto._abort_noise_handshake(client, "Noise handshake failed: bad PSK")
        entries = proto.get_recent_rejections()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["reason"], "Noise handshake failed: bad PSK")

    def test_decode_rejection_recorded(self):
        proto = _make_protocol()
        client = _make_client(proto)
        client.noise_transport = MagicMock()
        with self.assertRaises(Exception):
            client.decode("cleartext on a v3 session")
        entries = proto.get_recent_rejections()
        self.assertEqual(entries[0]["code"], 1008)
        self.assertIn("non-Noise", entries[0]["reason"])
        client.disconnect.assert_called_once_with(1008, entries[0]["reason"])

    def test_no_secret_in_ring(self):
        proto = _make_protocol()
        client = _make_client(proto)
        proto.handle_invalid_key_connected(client)
        self.assertNotIn("secret-access-key", repr(proto.get_recent_rejections()))

    def test_ring_is_bounded_and_newest_first(self):
        proto = _make_protocol()
        size = proto.rejection_history_size
        for i in range(size + 5):
            c = _make_client(proto)
            c.name = f"c{i}"
            proto.record_rejection(c, 1008, f"r{i}")
        entries = proto.get_recent_rejections()
        self.assertEqual(len(entries), size)
        self.assertEqual(entries[0]["reason"], f"r{size + 4}")

    def test_max_age_filters_old_entries(self):
        proto = _make_protocol()
        old = _make_client(proto)
        new = _make_client(proto)
        with patch("hivemind_core.protocol.time.time", return_value=time.time() - 3600):
            proto.record_rejection(old, 1008, "old")
        proto.record_rejection(new, 1008, "new")
        self.assertEqual([e["reason"] for e in proto.get_recent_rejections(max_age=60)],
                         ["new"])

    def test_nothing_sent_to_client(self):
        proto = _make_protocol()
        client = _make_client(proto)
        proto.handle_invalid_key_connected(client)
        client.send_msg.assert_not_called()


if __name__ == "__main__":
    unittest.main()
