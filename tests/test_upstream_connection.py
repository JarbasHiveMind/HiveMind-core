"""A node can be given an upstream connection from ``server.json``.

``bind_upstream`` already connects a node to a master above it, but only
Python could reach it, so ``hivemind-core listen`` was always a top-level
master. The ``upstream`` config block gives an operator that one bit.

Absent or disabled, the node stays exactly a top-level master.
"""
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from json_database import JsonConfigXDG

from hivemind_core.config import _DEFAULT
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


if __name__ == "__main__":
    unittest.main()
