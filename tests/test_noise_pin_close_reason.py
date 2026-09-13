"""The pin-mismatch close reaches the client and names no access key.

FAIL-BEFORE: the close reason held the whole operator hint with the access
key, over the 125-byte control frame limit, so tornado raised ValueError and
the client got 1008 "invalid message" on its next frame. The log line also
printed the access key.
"""
import unittest
from unittest.mock import MagicMock, patch

from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)

KEY = "a-long-secret-access-key-0123456789abcdef0123456789abcdef"


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.callbacks = MagicMock()
    return HiveMindListenerProtocol(agent_protocol=agent, db=MagicMock())


def _pin_mismatch(proto, client_id=None):
    client = HiveMindClientConnection(
        key=KEY, send_msg=MagicMock(), disconnect=MagicMock(),
        hm_protocol=proto)
    client.name = "sat-a"
    if client_id is not None:
        client._resolved_user = MagicMock(client_id=client_id)
    client.noise_handshake = MagicMock()
    transport = MagicMock()
    transport.remote_static_key = b"new-key"
    with patch("hivemind_core.protocol.NoiseTransport", return_value=transport), \
            patch.object(proto, "_get_pinned_client_noise_key", return_value=b"old-key"), \
            patch("hivemind_core.protocol.LOG") as log:
        proto._finish_noise_handshake(client)
    return client, log


class TestNoisePinCloseReason(unittest.TestCase):

    def test_close_reason_fits_a_control_frame(self):
        client, _ = _pin_mismatch(_make_protocol())
        code, reason = client.disconnect.call_args.args
        self.assertEqual(code, 1008)
        self.assertEqual(reason, "client Noise static key contradicts the pinned key")
        self.assertLessEqual(2 + len(reason.encode("utf-8")), 125)
        self.assertNotIn(KEY, reason)

    def test_log_line_names_client_id_not_key(self):
        _, log = _pin_mismatch(_make_protocol(), client_id=7)
        text = " ".join(str(c) for c in log.error.call_args_list)
        self.assertIn("reset-noise-pin 7", text)
        self.assertNotIn(KEY, text)

    def test_log_line_without_resolved_user_has_no_key(self):
        _, log = _pin_mismatch(_make_protocol())
        text = " ".join(str(c) for c in log.error.call_args_list)
        self.assertIn("reset-noise-pin <client id>", text)
        self.assertNotIn(KEY, text)

    def test_long_close_reason_is_cut_to_frame_limit(self):
        proto = _make_protocol()
        client = HiveMindClientConnection(
            key=KEY, send_msg=MagicMock(), disconnect=MagicMock(),
            hm_protocol=proto)
        proto._abort_noise_handshake(client, "log text", close_reason="é" * 200)
        reason = client.disconnect.call_args.args[1]
        self.assertLessEqual(len(reason.encode("utf-8")), 123)
        self.assertTrue(reason)


if __name__ == "__main__":
    unittest.main()
