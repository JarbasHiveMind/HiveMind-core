"""Failed handshakes are rate-limited per access key and per source IP
(HIVEMIND-CRYPTO-1 §3.4). A limited key or IP is refused before the node
sends Noise message 2."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_bus_client.noise import (
    NOISE_PATTERN_XX, NOISE_SUITES, build_prologue, noise_protocol_name,
    start_noise_handshake)

import hivemind_core.protocol as protocol_module
from hivemind_core.protocol import HiveMindClientConnection, HiveMindListenerProtocol

NODE_ID = "node-A"
SUITE = NOISE_SUITES[0]
PSK = bytes(range(32))
WRONG_PSK = bytes(32)
PASSWORD = "site-password"


class _Row:
    def __init__(self, metadata=None):
        self.metadata = metadata


class _Db:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_client_by_api_key(self, key):
        return self.row

    def update_item(self, user):
        pass


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class TestHandshakeRateLimit(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(HiveMindListenerProtocol, "_node_id",
                               new_callable=PropertyMock, return_value=NODE_ID)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.clock = _Clock()
        clock_patch = patch.object(protocol_module.time, "monotonic", self.clock)
        clock_patch.start()
        self.addCleanup(clock_patch.stop)
        # each initiator has a fresh static key; TOFU pinning is not under test
        for name in ("_get_pinned_client_noise_key", "_pin_client_noise_key"):
            pin_patch = patch.object(HiveMindListenerProtocol, name, return_value=None)
            pin_patch.start()
            self.addCleanup(pin_patch.stop)
        agent = MagicMock()
        self.row = _Row()
        self.proto = HiveMindListenerProtocol(agent_protocol=agent, db=_Db(self.row))
        self.row.metadata = {
            self.proto.NOISE_PSK_METADATA_KEY: PSK.hex(),
            self.proto.NOISE_PSK_BINDING_METADATA_KEY:
                self.proto._noise_psk_binding(PASSWORD.encode("utf-8"))}

    def _client(self, key, ip):
        client = HiveMindClientConnection(
            key=key, send_msg=MagicMock(), disconnect=MagicMock(),
            hm_protocol=self.proto, pswd_handshake=SimpleNamespace(password=PASSWORD))
        client.ip = ip
        client.send = MagicMock()
        client._hello_payload = {"node_id": NODE_ID}
        client._handshake_payload = {
            "max_protocol_version": 3,
            "noise": {"patterns": [NOISE_PATTERN_XX], "suites": [SUITE]}}
        return client

    def _attempt(self, key, ip, psk):
        """One handshake as a real initiator runs it; True when it completed."""
        client = self._client(key, ip)
        prologue = build_prologue(client._hello_payload, client._handshake_payload,
                                  noise_protocol_name(NOISE_PATTERN_XX, SUITE))
        initiator = start_noise_handshake(
            initiator=True, pattern=NOISE_PATTERN_XX, suite=SUITE, password=None,
            psk=psk, node_id=NODE_ID, prologue=prologue)
        msg1 = initiator.write_message(json.dumps({"binarize": False}).encode())
        self.proto.handle_noise_handshake_message(HiveMessage(HiveMessageType.HANDSHAKE, {
            "noise": {"pattern": NOISE_PATTERN_XX, "suite": SUITE, "msg": msg1.hex()}}),
            client)
        if not client.send.called:
            return client, False
        (msg2,), _ = client.send.call_args
        try:
            initiator.read_message(bytes.fromhex(msg2.payload["noise"]["msg"]))
        except Exception:
            self.proto.handle_client_disconnected(client)  # the initiator gives up
            return client, False
        self.proto.handle_noise_handshake_message(HiveMessage(HiveMessageType.HANDSHAKE, {
            "noise": {"msg": initiator.write_message(b"").hex()}}), client)
        return client, client.noise_transport is not None

    def test_key_is_refused_after_five_failures_until_the_window_passes(self):
        for _ in range(5):
            client, ok = self._attempt("key-a", "10.0.0.1", WRONG_PSK)
            self.assertFalse(ok)
            self.assertEqual(client.send.call_count, 1)  # it got message 2

        client, ok = self._attempt("key-a", "10.0.0.2", PSK)
        self.assertFalse(ok)
        client.send.assert_not_called()  # refused before message 2
        self.assertEqual(client.disconnect.call_args.args[0], 1008)
        self.assertEqual(self.proto.get_recent_rejections()[0]["reason"],
                         "handshake_rate_limited")

        # another key from another IP is not affected
        self.assertTrue(self._attempt("key-b", "10.0.0.3", PSK)[1])

        self.clock.now += 60
        self.assertTrue(self._attempt("key-a", "10.0.0.2", PSK)[1])

    def test_ip_is_refused_after_twenty_failures_and_success_does_not_reset(self):
        for i in range(19):
            self.assertFalse(self._attempt(f"key-{i}", "10.0.0.9", WRONG_PSK)[1])
        self.assertTrue(self._attempt("good-key", "10.0.0.9", PSK)[1])
        self.assertFalse(self._attempt("key-19", "10.0.0.9", WRONG_PSK)[1])
        client, ok = self._attempt("good-key", "10.0.0.9", PSK)
        self.assertFalse(ok)
        client.send.assert_not_called()
        self.assertTrue(self._attempt("good-key", "10.0.0.10", PSK)[1])

    def test_limits_come_from_the_server_config(self):
        cfg = {"handshake_failures_per_key": 2, "handshake_failures_per_ip": 0,
               "handshake_failure_window": 10}
        with patch.object(protocol_module, "get_server_config", return_value=cfg):
            proto = HiveMindListenerProtocol(agent_protocol=MagicMock(), db=_Db(self.row))
        self.assertEqual((proto._key_failures.limit, proto._key_failures.window), (2, 10))
        self.assertEqual(proto._ip_failures.limit, 0)


if __name__ == "__main__":
    unittest.main()
