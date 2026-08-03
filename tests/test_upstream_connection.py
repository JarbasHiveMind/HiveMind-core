"""A node can be given an upstream connection from ``server.json``.

``bind_upstream`` already connects a node to a master above it, but only
Python could reach it, so ``hivemind-core listen`` was always a top-level
master. The ``upstream`` config block gives an operator that one bit.

Absent or disabled, the node stays exactly a top-level master.
"""
import unittest
from unittest.mock import MagicMock, patch

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


class TestUpstreamConfigured(unittest.TestCase):
    def test_a_configured_node_binds_the_upstream(self):
        service = _make_service()
        hm_protocol = MagicMock()

        with patch("hivemind_core.service.get_server_config",
                   return_value=_config(UPSTREAM)), \
                patch("hivemind_core.service.HiveMessageBusClient") as client, \
                patch("hivemind_core.service.create_daemon") as daemon:
            slave = service._connect_upstream(hm_protocol)

        client.assert_called_once_with(key="an-access-key",
                                       password="a-password",
                                       host="ws://10.0.0.1",
                                       port=5678,
                                       self_signed=True)
        self.assertIs(slave.hm, client.return_value)
        hm_protocol.bind_upstream.assert_called_once_with(slave)
        # connecting happens off the startup thread, so an unreachable
        # upstream can not hold the node down
        daemon.assert_called_once()

    def test_ssl_selects_the_wss_scheme(self):
        service = _make_service()

        with patch("hivemind_core.service.get_server_config",
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

        with patch("hivemind_core.service.get_server_config",
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
