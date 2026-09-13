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
        self.assertEqual(entry["reason"], "protocol_v3_required")
        self.assertEqual(entry["peer"], client.peer)
        self.assertEqual(set(entry), {"time", "peer", "code", "reason"})

    def test_invalid_key_recorded_once(self):
        proto = _make_protocol()
        client = _make_client(proto)
        proto.handle_invalid_key_connected(client)
        proto.handle_invalid_key_connected(client)
        entries = proto.get_recent_rejections()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["reason"], "invalid_key")

    def test_noise_abort_stores_code_not_text(self):
        proto = _make_protocol()
        client = _make_client(proto)
        proto._abort_noise_handshake(client, "handshake failure: secret-access-key")
        entries = proto.get_recent_rejections()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["reason"], "noise_handshake_failed")
        # the client still gets the full close reason, as before
        client.disconnect.assert_called_once_with(
            1008, "handshake failure: secret-access-key")

    def test_decode_rejection_recorded(self):
        proto = _make_protocol()
        client = _make_client(proto)
        client.noise_transport = MagicMock()
        with self.assertRaises(Exception):
            client.decode("cleartext on a v3 session")
        entries = proto.get_recent_rejections()
        self.assertEqual(entries[0]["code"], 1008)
        self.assertEqual(entries[0]["reason"], "non_noise_frame")
        client.disconnect.assert_called_once()

    def test_unknown_reason_stored_as_other(self):
        proto = _make_protocol()
        client = _make_client(proto)
        proto.record_rejection(client, 1008, "free text with secret-access-key")
        self.assertEqual(proto.get_recent_rejections()[0]["reason"], "other")

    def test_no_key_in_ring_on_any_rejection_path(self):
        """FAIL-BEFORE: the pin-mismatch close reason names the access key
        ('reset-noise-pin <key>'), and the ring stored that text."""
        proto = _make_protocol()
        key = "secret-access-key"

        def fresh(**kw):
            c = _make_client(proto, **kw)
            c.name = f"c{len(proto.recent_rejections)}"
            return c

        # sub-v3
        with patch("hivemind_core.protocol.NOISE_SUPPORTED", True):
            proto.handle_new_client(fresh(pswd_handshake=None))
        # invalid key (transport hook)
        proto.handle_invalid_key_connected(fresh())
        # Noise abort with text that names the key
        proto._abort_noise_handshake(fresh(), f"handshake failure: {key}")
        # pin mismatch: the real code path in the handshake completion
        c = fresh()
        c.noise_handshake = MagicMock()
        transport = MagicMock()
        transport.remote_static_key = b"new-key"
        with patch("hivemind_core.protocol.NoiseTransport", return_value=transport), \
                patch.object(proto, "_get_pinned_client_noise_key", return_value=b"old-key"):
            proto._finish_noise_handshake(c)
        # decode-time closes
        for transport_obj, payload in ((MagicMock(), "text on v3"),):
            c = fresh()
            c.noise_transport = transport_obj
            with self.assertRaises(Exception):
                c.decode(payload)
        # 1011 internal error
        c = fresh()
        with patch.object(proto, "handle_unknown_message", side_effect=RuntimeError(key)):
            msg = MagicMock()
            msg.msg_type = "weird"
            proto.handle_message(msg, c)

        entries = proto.get_recent_rejections()
        reasons = {e["reason"] for e in entries}
        self.assertIn("noise_pin_mismatch", reasons)
        self.assertIn("internal_error", reasons)
        self.assertGreaterEqual(len(entries), 6)
        for e in entries:
            self.assertIn(e["reason"], proto.REJECTION_REASONS)
            self.assertNotIn(key, repr(e))

    def test_ring_is_bounded_and_newest_first(self):
        proto = _make_protocol()
        size = proto.rejection_history_size
        for i in range(size + 5):
            c = _make_client(proto)
            c.name = f"c{i}"
            proto.record_rejection(c, 1008, "invalid_key")
        entries = proto.get_recent_rejections()
        self.assertEqual(len(entries), size)
        self.assertEqual(entries[0]["peer"], c.peer)

    def test_max_age_filters_old_entries(self):
        proto = _make_protocol()
        old = _make_client(proto)
        new = _make_client(proto)
        with patch("hivemind_core.protocol.time.time", return_value=time.time() - 3600):
            proto.record_rejection(old, 1008, "invalid_key")
        new.name = "newer-client"
        proto.record_rejection(new, 1008, "invalid_key")
        self.assertEqual([e["peer"] for e in proto.get_recent_rejections(max_age=60)],
                         [new.peer])

    def test_nothing_sent_to_client(self):
        proto = _make_protocol()
        client = _make_client(proto)
        proto.handle_invalid_key_connected(client)
        client.send_msg.assert_not_called()


if __name__ == "__main__":
    unittest.main()
