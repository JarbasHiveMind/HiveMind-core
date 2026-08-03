"""A node can be given an upstream connection from ``server.json``.

``bind_upstream`` already connects a node to a master above it, but only
Python could reach it, so ``hivemind-core listen`` was always a top-level
master. The ``upstream`` config block gives an operator that one bit.

Absent or disabled, the node stays exactly a top-level master.
"""
import json
import os
import socket
import tempfile
import threading
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from json_database import JsonConfigXDG

from hivemind_bus_client.client import HiveMessageBusClient
from hivemind_core.config import _DEFAULT, get_server_config, upstream_config
from hivemind_core.service import HiveMindService

UPSTREAM = {
    "enabled": True,
    "host": "10.0.0.1",
    "port": 5678,
    "key": "an-access-key",
    "password": "a-password",
    "ssl": False,
    "self_signed": True,
}


def _make_service():
    service = HiveMindService(db=MagicMock(), identity=MagicMock())
    service.identity.site_id = "a-site"
    return service


def _config(upstream):
    return {**_DEFAULT, "upstream": upstream}


@contextmanager
def scratch_config_home():
    """Keep the upstream identity file out of the developer's real
    ~/.config/hivemind — building it writes to disk.

    ``JsonConfigXDG`` resolves ``xdg_folder`` as a default argument, i.e. once
    at import time, so patching ``XDG_CONFIG_HOME`` in the environment here
    would come too late. Redirect the folder explicitly instead.
    """
    with tempfile.TemporaryDirectory() as tmp:
        with patch("hivemind_core.service.JsonConfigXDG",
                   lambda name, subfolder: JsonConfigXDG(
                       name, xdg_folder=tmp, subfolder=subfolder)):
            yield tmp


class TestUpstreamDefaults(unittest.TestCase):
    def test_the_default_config_has_no_upstream_enabled(self):
        self.assertFalse(_DEFAULT["upstream"]["enabled"])

    def test_a_node_without_upstream_config_stays_a_top_level_master(self):
        service = _make_service()
        hm_protocol = MagicMock()
        hm_protocol._upstream_hm = None

        with patch("hivemind_core.service.get_server_config",
                   return_value=_DEFAULT):
            self.assertIsNone(service._connect_upstream(hm_protocol))

        hm_protocol.bind_upstream.assert_not_called()
        self.assertIsNone(hm_protocol._upstream_hm)

    def test_a_disabled_upstream_block_binds_nothing(self):
        service = _make_service()
        hm_protocol = MagicMock()
        config = _config({**UPSTREAM, "enabled": False})

        with patch("hivemind_core.service.get_server_config",
                   return_value=config):
            self.assertIsNone(service._connect_upstream(hm_protocol))

        hm_protocol.bind_upstream.assert_not_called()


    def test_enabled_without_credentials_stays_a_top_level_master(self):
        """Regression, found by live testing: HiveMessageBusClient raises at
        construction when key or password is missing. Left to propagate, one
        typo in server.json aborted startup and took every satellite offline.
        """
        for missing in ("key", "password"):
            with self.subTest(missing=missing):
                service = _make_service()
                hm_protocol = MagicMock()
                config = _config({**UPSTREAM, missing: ""})

                with patch("hivemind_core.service.get_server_config",
                           return_value=config), \
                        patch("hivemind_core.service.HiveMessageBusClient") as c:
                    self.assertIsNone(service._connect_upstream(hm_protocol))

                c.assert_not_called()
                hm_protocol.bind_upstream.assert_not_called()


class TestUpstreamConfigured(unittest.TestCase):
    def test_a_configured_node_binds_the_upstream(self):
        service = _make_service()
        hm_protocol = MagicMock()

        with scratch_config_home(), \
                patch("hivemind_core.service.get_server_config",
                      return_value=_config(UPSTREAM)), \
                patch("hivemind_core.service.HiveMessageBusClient") as client, \
                patch("hivemind_core.service.create_daemon") as daemon:
            slave = service._connect_upstream(hm_protocol)

        self.assertEqual(client.call_args.kwargs["key"], "an-access-key")
        self.assertEqual(client.call_args.kwargs["password"], "a-password")
        self.assertEqual(client.call_args.kwargs["host"], "ws://10.0.0.1")
        self.assertEqual(client.call_args.kwargs["port"], 5678)
        self.assertTrue(client.call_args.kwargs["self_signed"])
        self.assertIs(slave.hm, client.return_value)
        hm_protocol.bind_upstream.assert_called_once_with(slave)
        # connecting happens off the startup thread, so an unreachable
        # upstream can not hold the node down
        daemon.assert_called_once()

    def test_the_upstream_client_gets_its_own_identity_file(self):
        """Regression, found by live testing against two real nodes.

        ``HiveMessageBusClient`` copies the credentials it is given onto the
        identity it holds, and the first Noise handshake saves that identity
        to disk. Handed the node's own identity, it overwrote the node's
        ``password`` and ``access_key``, and every downstream satellite then
        failed its handshake with "invalid api key".
        """
        service = _make_service()

        with scratch_config_home(), \
                patch("hivemind_core.service.get_server_config",
                      return_value=_config(UPSTREAM)), \
                patch("hivemind_core.service.HiveMessageBusClient") as client, \
                patch("hivemind_core.service.create_daemon"):
            service._connect_upstream(MagicMock())

        identity = client.call_args.kwargs["identity"]
        self.assertTrue(identity.IDENTITY_FILE.path.endswith(
            "_identity_upstream.json"), identity.IDENTITY_FILE.path)

    def test_ssl_selects_the_wss_scheme(self):
        service = _make_service()

        with scratch_config_home(), \
                patch("hivemind_core.service.get_server_config",
                      return_value=_config({**UPSTREAM, "ssl": True})), \
                patch("hivemind_core.service.HiveMessageBusClient") as client, \
                patch("hivemind_core.service.create_daemon"):
            service._connect_upstream(MagicMock())

        self.assertEqual(client.call_args.kwargs["host"], "wss://10.0.0.1")

    def test_an_unreachable_upstream_does_not_stop_the_node(self):
        """The connect worker keeps retrying; a failure there is logged, and
        the node stays up serving its downstream clients."""
        service = _make_service()
        hm_protocol = MagicMock()
        started = []

        with scratch_config_home(), \
                patch("hivemind_core.service.get_server_config",
                      return_value=_config(UPSTREAM)), \
                patch("hivemind_core.service.HiveMessageBusClient") as client, \
                patch("hivemind_core.service.create_daemon",
                      side_effect=lambda fn: started.append(fn)):
            client.return_value.connect.side_effect = ConnectionRefusedError(
                "upstream is down")
            service._connect_upstream(hm_protocol)

        self.assertEqual(len(started), 1)
        started[0]()  # the worker must swallow the failure, not raise


#: hand-edited `upstream` blocks an operator can realistically leave behind.
#: Every one of them used to raise out of `_connect_upstream`, which runs
#: BEFORE the network protocols start, so the whole node never came up.
PARTIAL_BLOCKS = {
    "no ssl/self_signed": {"enabled": True, "host": "h", "port": 1,
                           "key": "k", "password": "p"},
    "only enabled/host/port": {"enabled": True, "host": "h", "port": 1},
    "only enabled": {"enabled": True},
    "empty block": {},
    "null": None,
}


class TestPartialUpstreamBlock(unittest.TestCase):
    """A partial block must not take the node offline.

    ``upstream_config`` deep-merges the block against the defaults, the way
    the ``policy`` block is deep-merged, so every sub-key the use site indexes
    is always there.
    """

    def test_every_partial_block_is_completed_with_the_defaults(self):
        for label, block in PARTIAL_BLOCKS.items():
            with self.subTest(block=label):
                merged = upstream_config({"upstream": block})
                self.assertEqual(set(merged), set(_DEFAULT["upstream"]))
                for key, default in _DEFAULT["upstream"].items():
                    if not isinstance(block, dict) or key not in block:
                        self.assertEqual(merged[key], default)

    def test_a_missing_block_gives_the_defaults(self):
        self.assertEqual(upstream_config({}), _DEFAULT["upstream"])

    def test_a_set_sub_key_survives_the_merge(self):
        merged = upstream_config({"upstream": {"enabled": True, "port": 9}})
        self.assertTrue(merged["enabled"])
        self.assertEqual(merged["port"], 9)
        self.assertEqual(merged["ssl"], _DEFAULT["upstream"]["ssl"])

    def test_get_server_config_merges_the_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "hivemind-core")
            os.makedirs(folder)
            with open(os.path.join(folder, "server.json"), "w") as f:
                json.dump({"upstream": {"enabled": True, "host": "10.0.0.1"}}, f)
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
                upstream = get_server_config()["upstream"]
        self.assertEqual(set(upstream), set(_DEFAULT["upstream"]))
        self.assertTrue(upstream["enabled"])
        self.assertEqual(upstream["host"], "10.0.0.1")
        self.assertEqual(upstream["port"], _DEFAULT["upstream"]["port"])

    def test_no_partial_block_aborts_startup(self):
        for label, block in PARTIAL_BLOCKS.items():
            with self.subTest(block=label):
                service = _make_service()
                with scratch_config_home(), \
                        patch("hivemind_core.service.get_server_config",
                              return_value={**_DEFAULT, "upstream": block}), \
                        patch("hivemind_core.service.HiveMessageBusClient"), \
                        patch("hivemind_core.service.create_daemon"):
                    service._connect_upstream(MagicMock())  # must not raise


class TestUpstreamIsNotThisNode(unittest.TestCase):
    """An upstream aimed at this node's own listener connects, is rejected,
    and reconnects every five seconds forever, putting a
    ``hive.client.connection.error`` on the bus each time. Refuse at startup.
    """

    LISTENERS = {"hivemind-websocket-plugin": {"host": "0.0.0.0", "port": 5678},
                 "hivemind-http-plugin": {"host": "127.0.0.1", "port": 5679}}

    def _connect(self, host, port):
        service = _make_service()
        hm_protocol = MagicMock()
        config = {**_DEFAULT,
                  "network_protocol": self.LISTENERS,
                  "upstream": {**UPSTREAM, "host": host, "port": port}}
        with scratch_config_home(), \
                patch("hivemind_core.service.get_server_config",
                      return_value=config), \
                patch("hivemind_core.service.HiveMessageBusClient") as client, \
                patch("hivemind_core.service.create_daemon"):
            result = service._connect_upstream(hm_protocol)
        return result, client, hm_protocol

    def test_loopback_matches_a_listener_bound_to_all_interfaces(self):
        """The listener is on 0.0.0.0 and the upstream says 127.0.0.1 — the
        same socket, so comparing the host strings is not enough."""
        result, client, hm_protocol = self._connect("127.0.0.1", 5678)
        self.assertIsNone(result)
        client.assert_not_called()
        hm_protocol.bind_upstream.assert_not_called()

    def test_every_way_of_naming_this_node_is_refused(self):
        for host in ("127.0.0.1", "localhost", "0.0.0.0", socket.gethostname()):
            for port in (5678, 5679):
                with self.subTest(host=host, port=port):
                    self.assertIsNone(self._connect(host, port)[0])

    def test_a_loopback_port_nothing_listens_on_is_allowed(self):
        """Only this node's OWN listeners are refused; another hive node on
        the same machine is a legitimate master."""
        result, client, _ = self._connect("127.0.0.1", 5999)
        self.assertIsNotNone(result)
        client.assert_called_once()

    def test_a_remote_master_on_the_same_port_is_allowed(self):
        result, client, _ = self._connect("10.0.0.1", 5678)
        self.assertIsNotNone(result)
        client.assert_called_once()


class TestAgainstTheRealClient(unittest.TestCase):
    """Every other test in this file mocks ``HiveMessageBusClient``, so a
    config block of the wrong SHAPE never reached the code that reads it. One
    test builds the real client, against an endpoint nothing listens on."""

    UNREACHABLE_PORT = 45999

    def _server_config(self, upstream):
        return {**_DEFAULT,
                "network_protocol": {"hivemind-websocket-plugin":
                                     {"host": "0.0.0.0", "port": 5678}},
                "upstream": upstream}

    def test_a_real_client_is_built_and_the_node_stays_up(self):
        service = _make_service()
        hm_protocol = MagicMock()
        workers = []
        upstream = {"enabled": True, "host": "127.0.0.1",
                    "port": self.UNREACHABLE_PORT,
                    "key": "an-access-key", "password": "a-password"}

        with scratch_config_home(), \
                patch("hivemind_core.service.get_server_config",
                      return_value=self._server_config(upstream)), \
                patch("hivemind_core.service.create_daemon",
                      side_effect=workers.append):
            slave = service._connect_upstream(hm_protocol)

            # the block above has no `ssl` and no `self_signed`: reading it
            # raised KeyError here before the deep merge, aborting startup
            self.assertIsNotNone(slave)
            self.assertIsInstance(slave.hm, HiveMessageBusClient)
            hm_protocol.bind_upstream.assert_called_once_with(slave)

            # and the worker really tries to reach a dead endpoint without
            # raising into the caller
            self.assertEqual(len(workers), 1)
            worker = threading.Thread(target=workers[0], daemon=True)
            worker.start()
            worker.join(timeout=10)


if __name__ == "__main__":
    unittest.main()
