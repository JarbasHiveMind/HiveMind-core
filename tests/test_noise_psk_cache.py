"""The Noise PSK must be derived once per password, not once per connection.

Regression coverage for the fix: handle_noise_handshake_message used to pass
``password=`` to ``start_noise_handshake``, so every accepted connection ran
``derive_psk`` -- argon2id with time_cost=3 and a 64 MiB arena, measured
152-333ms -- on the single tornado IOLoop thread that serves every connected
client.

The salt is SHA-256(node_id), so the derived key depends only on the password
and this node's id. Both are constant for the life of the node, which makes
the result cacheable. The cache is keyed on the password as well as the node
id: Client rows carry their own password, so handing a client the PSK derived
from another client's password would silently break its handshake.
"""
import tempfile
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from hivemind_bus_client.identity import NodeIdentity

import hivemind_core.protocol as protocol_module
from hivemind_core.protocol import HiveMindListenerProtocol


def _make_protocol(identity_path, node_id="node-A"):
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.get_bus.return_value = agent.bus
    agent.callbacks = MagicMock()

    db = MagicMock()
    db.get_client_by_api_key.return_value = MagicMock(allowed_types=[], is_admin=False)

    identity = NodeIdentity()
    identity.private_key = identity_path

    proto = HiveMindListenerProtocol(agent_protocol=agent, db=db,
                                     identity=identity)
    patcher = patch.object(HiveMindListenerProtocol, "_node_id",
                           new_callable=PropertyMock, return_value=node_id)
    patcher.start()
    return proto, patcher


class TestNoisePSKCache(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.protocol, patcher = _make_protocol(f"{self._tmpdir.name}/node.pem")
        self.addCleanup(patcher.stop)

    def test_derived_once_across_many_connections(self):
        with patch.object(protocol_module, "derive_psk",
                          wraps=protocol_module.derive_psk) as spy:
            psks = [self.protocol.noise_psk("site-password") for _ in range(10)]

        self.assertEqual(spy.call_count, 1)
        self.assertEqual(len(set(psks)), 1)

    def test_different_passwords_get_different_psks(self):
        alice = self.protocol.noise_psk("alice-password")
        bob = self.protocol.noise_psk("bob-password")

        self.assertNotEqual(alice, bob)
        # and each client keeps getting its own key back, not the other's
        self.assertEqual(self.protocol.noise_psk("alice-password"), alice)
        self.assertEqual(self.protocol.noise_psk("bob-password"), bob)

    def test_matches_an_uncached_derivation(self):
        from poorman_handshake.noise import derive_psk

        self.assertEqual(self.protocol.noise_psk("site-password"),
                         derive_psk(b"site-password", node_id="node-A"))

    def test_str_and_bytes_passwords_share_one_entry(self):
        with patch.object(protocol_module, "derive_psk",
                          wraps=protocol_module.derive_psk) as spy:
            text = self.protocol.noise_psk("site-password")
            raw = self.protocol.noise_psk(b"site-password")

        self.assertEqual(text, raw)
        self.assertEqual(spy.call_count, 1)

    def test_cache_stays_bounded(self):
        limit = HiveMindListenerProtocol.NOISE_PSK_CACHE_SIZE
        fake = patch.object(protocol_module, "derive_psk",
                            side_effect=lambda pwd, node_id: pwd.ljust(32, b"."))
        with fake:
            for i in range(limit + 50):
                self.protocol.noise_psk(f"password-{i}")

        self.assertEqual(len(self.protocol._noise_psks), limit)
        # the oldest entries were evicted, the newest are still there
        self.assertNotIn((b"password-0", "node-A"), self.protocol._noise_psks)
        self.assertIn((f"password-{limit + 49}".encode(), "node-A"),
                      self.protocol._noise_psks)

    def test_recently_used_entries_survive_eviction(self):
        limit = HiveMindListenerProtocol.NOISE_PSK_CACHE_SIZE
        fake = patch.object(protocol_module, "derive_psk",
                            side_effect=lambda pwd, node_id: pwd.ljust(32, b"."))
        with fake:
            self.protocol.noise_psk("long-lived")
            for i in range(limit):
                self.protocol.noise_psk(f"password-{i}")
                self.protocol.noise_psk("long-lived")

        self.assertIn((b"long-lived", "node-A"), self.protocol._noise_psks)

    def test_the_password_never_reaches_the_logs(self):
        lines = []
        with patch.object(protocol_module.LOG, "debug", lines.append), \
                patch.object(protocol_module.LOG, "info", lines.append), \
                patch.object(protocol_module.LOG, "warning", lines.append), \
                patch.object(protocol_module.LOG, "error", lines.append):
            psk = self.protocol.noise_psk("very-secret-password")

        self.assertEqual(lines, [])
        self.assertEqual(len(psk), 32)


if __name__ == "__main__":
    unittest.main()
