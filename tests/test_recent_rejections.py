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

    def test_a_pre_authorization_rejection_keeps_its_name(self):
        """A network protocol plugin records this one with a stand-in peer.

        A websocket whose ``authorization`` argument cannot be decoded is
        refused before a HiveMindClientConnection exists, so the plugin gives
        record_rejection an object that carries only ``peer`` and
        ``rejection_recorded``. The reason must survive as itself, so the
        operator can tell it from every other unclassified failure.
        """

        class _UnauthenticatedPeer:
            __slots__ = ("peer", "rejection_recorded")

            def __init__(self, peer):
                self.peer = peer
                self.rejection_recorded = False

        proto = _make_protocol()
        proto.record_rejection(
            _UnauthenticatedPeer("203.0.113.9"), 1008, "invalid_authorization")
        entries = proto.get_recent_rejections()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["reason"], "invalid_authorization")
        self.assertEqual(entries[0]["peer"], "203.0.113.9")

    def test_an_unknown_reason_is_still_stored_as_other(self):
        proto = _make_protocol()
        proto.record_rejection(_make_client(proto), 1008, "invented_reason")
        self.assertEqual(proto.get_recent_rejections()[0]["reason"], "other")

    def test_nothing_sent_to_client(self):
        proto = _make_protocol()
        client = _make_client(proto)
        proto.handle_invalid_key_connected(client)
        client.send_msg.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class TestAHandshakeFailureIsNotAnInvalidKey(unittest.TestCase):
    """A v3 abort must not tell the operator the access key is wrong.

    The key is looked up and accepted when the transport opens the
    connection. A handshake that then fails says nothing about the key, and
    reporting it as an invalid key sent at least one operator hunting a key
    that was already correct (hivemind-homeassistant#2 is the open-time
    case; this is the other path to the same words).
    """

    def _abort(self, reason="this node requires the v3 Noise handshake"):
        proto = _make_protocol()
        client = _make_client(proto)
        emitted = []
        logged = []
        with patch.object(proto, "_emit_lifecycle",
                          side_effect=lambda c, m: emitted.append(m)), \
                patch("hivemind_core.protocol.LOG.error", side_effect=logged.append):
            proto._abort_noise_handshake(client, reason)
        return proto, client, emitted, logged

    def test_the_bus_error_names_the_handshake_not_the_key(self):
        _, _, emitted, _ = self._abort()
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0].data["error"], "protocol v3 handshake failed")

    def test_the_log_does_not_claim_an_invalid_key(self):
        _, _, _, logged = self._abort()
        self.assertTrue(logged, "the abort logged nothing")
        self.assertFalse(
            any("invalid api key" in line for line in logged),
            f"a handshake abort still reports an invalid key: {logged}")
        self.assertTrue(any("Noise handshake failed" in line for line in logged))

    def test_the_handshake_reason_never_reaches_the_bus_or_the_second_line(self):
        """The reason is free text and can name the access key."""
        _, _, emitted, logged = self._abort(
            reason="pinned key mismatch for secret-access-key")
        self.assertNotIn("secret-access-key", emitted[0].data["error"])
        second_lines = [line for line in logged if "FAILED:" not in line]
        self.assertTrue(second_lines)
        for line in second_lines:
            self.assertNotIn("secret-access-key", line)

    def test_the_rejection_ring_still_says_handshake(self):
        proto, _, _, _ = self._abort()
        entries = proto.get_recent_rejections()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["reason"], "noise_handshake_failed")

    def test_the_open_time_path_is_unchanged(self):
        proto = _make_protocol()
        client = _make_client(proto)
        emitted = []
        logged = []
        with patch.object(proto, "_emit_lifecycle",
                          side_effect=lambda c, m: emitted.append(m)), \
                patch("hivemind_core.protocol.LOG.error", side_effect=logged.append):
            proto.handle_invalid_key_connected(client)
        self.assertEqual(emitted[0].data["error"], "invalid access key")
        self.assertIn("Client provided an invalid api key", logged)
        self.assertEqual(proto.get_recent_rejections()[0]["reason"], "invalid_key")

    def test_both_paths_still_fire_the_invalid_key_callbacks(self):
        """Dropping these would make rejections vanish from the panel's counters."""
        for abort in (True, False):
            proto = _make_protocol()
            proto.callbacks = MagicMock()
            client = _make_client(proto)
            with patch.object(proto, "_emit_lifecycle"):
                if abort:
                    proto._abort_noise_handshake(client, "some reason")
                else:
                    proto.handle_invalid_key_connected(client)
            proto.callbacks.on_invalid_key.assert_called_once_with(client)
            proto.agent_protocol.callbacks.on_invalid_key.assert_called_once_with(client)
