"""Tests for hivemind_core.config back-compat shims."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hivemind_core.config import _DEFAULT, get_server_config


class TestPolicyConfigBackCompat(unittest.TestCase):
    """Legacy server.json files may carry policy.fail_open (removed) or
    be missing policy.chain (default to OVOSAgentPolicy)."""

    @staticmethod
    def _stub_xdg(tmpdir, body):
        path = Path(tmpdir) / "hivemind-core" / "server.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if body is not None:
            path.write_text(json.dumps(body))
        return path

    def test_fail_open_is_stripped(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._stub_xdg(tmp, {
                "policy": {"fail_open": True,
                           "chain": [{"module": "x"}]},
            })
            with patch("hivemind_core.config.xdg_config_home",
                       return_value=tmp):
                cfg = get_server_config()
            self.assertNotIn("fail_open", cfg["policy"])

    def test_missing_chain_gets_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._stub_xdg(tmp, {"policy": {}})
            with patch("hivemind_core.config.xdg_config_home",
                       return_value=tmp):
                cfg = get_server_config()
            self.assertEqual(cfg["policy"]["chain"],
                             _DEFAULT["policy"]["chain"])

    def test_explicit_chain_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._stub_xdg(tmp, {
                "policy": {"chain": [{"module": "operator-policy"}]},
            })
            with patch("hivemind_core.config.xdg_config_home",
                       return_value=tmp):
                cfg = get_server_config()
            self.assertEqual(cfg["policy"]["chain"],
                             [{"module": "operator-policy"}])

    def test_non_dict_policy_is_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._stub_xdg(tmp, {"policy": "garbage"})
            with patch("hivemind_core.config.xdg_config_home",
                       return_value=tmp):
                cfg = get_server_config()
            self.assertIsInstance(cfg["policy"], dict)
            self.assertIn("chain", cfg["policy"])


if __name__ == "__main__":
    unittest.main()


class TestPartiallySpecifiedBlocksKeepTheirDefaults:
    """A server.json that overrides one plugin setting must still start.

    Overriding a single value is the documented way to change the bind
    address::

        {"network_protocol": {"hivemind-websocket-plugin": {"port": 5678}}}

    That block has no ``module``, and ``get_network_protocol`` reads
    ``config["module"]`` directly, so before this fix the service died at
    startup with a bare KeyError instead of using the default plugin.
    """

    def _config(self, tmp_path, monkeypatch, written):
        import json
        from hivemind_core import config as cfg_mod
        cfgdir = tmp_path / "hivemind-core"
        cfgdir.mkdir(parents=True)
        (cfgdir / "server.json").write_text(json.dumps(written))
        monkeypatch.setattr(cfg_mod, "xdg_config_home", lambda: str(tmp_path))
        return cfg_mod.get_server_config()

    def test_a_partial_agent_block_keeps_its_module(self, tmp_path, monkeypatch):
        cfg = self._config(tmp_path, monkeypatch, {
            "agent_protocol": {"hivemind-ovos-agent-plugin": {"port": 8181}},
        })
        assert cfg["agent_protocol"]["module"] == "hivemind-ovos-agent-plugin"

    def test_the_users_own_values_still_win(self, tmp_path, monkeypatch):
        cfg = self._config(tmp_path, monkeypatch, {
            "agent_protocol": {"module": "my-plugin"},
        })
        assert cfg["agent_protocol"]["module"] == "my-plugin"

    def test_a_partial_network_block_keeps_the_other_transports(
            self, tmp_path, monkeypatch):
        """network_protocol is multi-transport and has no ``module``; naming
        one transport must not silently drop the others' defaults."""
        cfg = self._config(tmp_path, monkeypatch, {
            "network_protocol": {"hivemind-websocket-plugin": {"port": 9999}},
        })
        assert cfg["network_protocol"]["hivemind-websocket-plugin"]["port"] == 9999
        assert "hivemind-http-plugin" in cfg["network_protocol"]

    def test_a_config_missing_a_whole_block_still_starts(self, tmp_path, monkeypatch):
        cfg = self._config(tmp_path, monkeypatch, {"min_protocol_version": 2})
        assert cfg["agent_protocol"]["module"]
        assert "binary_protocol" in cfg
        assert cfg["min_protocol_version"] == 2

    def test_binary_protocol_module_none_is_preserved_not_overwritten(
            self, tmp_path, monkeypatch):
        """None is a meaningful value here (binary protocol is optional)."""
        cfg = self._config(tmp_path, monkeypatch,
                           {"binary_protocol": {"module": None}})
        assert cfg["binary_protocol"]["module"] is None
