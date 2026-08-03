"""The node's RSA identity key must be imported once, not once per connection.

Regression coverage for the fix: HiveMindClientConnection.__post_init__ used
to build ``HandShake(self.hm_protocol.identity.private_key)`` on every new
connection. ``HandShake.__init__`` re-reads and re-validates the 2048-bit PEM
key (measured 35-58ms) on the single tornado IOLoop thread that serves every
connected client, freezing the node on every accept.

The fix shares the already-imported, immutable RSA key object across
connections while keeping each connection's ``HandShake`` instance distinct
-- ``target_key``/``secret`` are per-peer mutable state and must never be
shared, or concurrent connects would clobber each other's session secret and
peer key.
"""
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from hivemind_bus_client.identity import NodeIdentity
from poorman_handshake import HandShake

from hivemind_core.protocol import HiveMindClientConnection, HiveMindListenerProtocol


def _make_protocol(identity_path):
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.get_bus.return_value = agent.bus
    agent.callbacks = MagicMock()

    db = MagicMock()
    db.get_client_by_api_key.return_value = MagicMock(allowed_types=[], is_admin=False)

    identity = NodeIdentity()
    identity.private_key = identity_path

    return HiveMindListenerProtocol(agent_protocol=agent, db=db,
                                    require_crypto=False,
                                    handshake_enabled=False,
                                    identity=identity)


def _make_client(protocol, key="test-key", name="test-client"):
    return HiveMindClientConnection(
        key=key,
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=protocol,
        name=name,
    )


class TestRSAKeyImportedOncePerNode(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.identity_path = f"{self._tmpdir.name}/node.pem"
        # pre-create the key file so later HandShake() calls take the
        # load-from-disk path (RSA.import_key) rather than first-run
        # generation (RSA.generate) -- that's the path we're testing
        with self.assertWarns(DeprecationWarning):
            HandShake(self.identity_path)

    def test_rsa_import_key_called_once_not_per_connection(self):
        from Cryptodome.PublicKey import RSA
        protocol = _make_protocol(self.identity_path)

        with patch.object(RSA, "import_key", wraps=RSA.import_key) as spy:
            clients = [_make_client(protocol, key=f"k{i}") for i in range(10)]

        # the key is imported lazily, on first use, then cached -- the first
        # of these 10 connections triggers exactly one import, none of the
        # other nine re-import it
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(len({id(c.handshake.private_key) for c in clients}), 1)

    def test_each_connection_gets_a_distinct_handshake_instance(self):
        protocol = _make_protocol(self.identity_path)
        a = _make_client(protocol, key="a")
        b = _make_client(protocol, key="b")

        self.assertIsNot(a.handshake, b.handshake)
        # the shared object is only the immutable key
        self.assertIs(a.handshake.private_key, b.handshake.private_key)
        self.assertIsNone(a.handshake.target_key)
        self.assertIsNone(b.handshake.target_key)
        self.assertIsNone(a.handshake.secret)
        self.assertIsNone(b.handshake.secret)

    def test_concurrent_handshakes_do_not_corrupt_each_others_secret(self):
        protocol = _make_protocol(self.identity_path)
        clients = [_make_client(protocol, key=f"c{i}") for i in range(8)]

        with self.assertWarns(DeprecationWarning):
            peer_key = HandShake(f"{self._tmpdir.name}/peer.pem").private_key.public_key()

        errors = []

        def do_handshake(client):
            try:
                for _ in range(20):
                    client.handshake.generate_handshake(pub=peer_key)
            except Exception as e:  # pragma: no cover - failure path
                errors.append(e)

        threads = [threading.Thread(target=do_handshake, args=(c,)) for c in clients]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        secrets = [c.handshake.secret for c in clients]
        self.assertEqual(len(secrets), len(set(secrets)))
        for c in clients:
            self.assertIsNone(c.handshake.target_key)  # generate_handshake never touches it


if __name__ == "__main__":
    unittest.main()
