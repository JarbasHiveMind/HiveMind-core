"""Tests for hivemind_core.config back-compat shims."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from json_database import JsonStorageXDG

from hivemind_core.config import (_DEFAULT, ServerConfigError,
                                  get_server_config)


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

    def test_naming_one_transport_does_not_enable_the_others(
            self, tmp_path, monkeypatch):
        """`network_protocol` sub-keys are the set of *enabled* transports.

        service.run() starts one transport per key, so backfilling this block
        would start a listener the operator never asked for (and log a
        traceback when its plugin is not installed).
        """
        cfg = self._config(tmp_path, monkeypatch, {
            "network_protocol": {"hivemind-websocket-plugin": {"port": 9999}},
        })
        assert cfg["network_protocol"]["hivemind-websocket-plugin"]["port"] == 9999
        assert list(cfg["network_protocol"]) == ["hivemind-websocket-plugin"], \
            "only the transports the operator configured may be present"

    def test_a_config_missing_a_whole_block_still_starts(self, tmp_path, monkeypatch):
        cfg = self._config(tmp_path, monkeypatch, {"binarize": True})
        assert cfg["agent_protocol"]["module"]
        assert "binary_protocol" in cfg
        assert cfg["binarize"] is True

    def test_binary_protocol_module_none_is_preserved_not_overwritten(
            self, tmp_path, monkeypatch):
        """None is a meaningful value here (binary protocol is optional)."""
        cfg = self._config(tmp_path, monkeypatch,
                           {"binary_protocol": {"module": None}})
        assert cfg["binary_protocol"]["module"] is None


class TestUnparsedServerJsonIsNeverWritten(unittest.TestCase):
    """A server.json that exists but does not parse holds the operator's
    settings; replacing it with first-run defaults loses them."""

    BROKEN = ('{"network_protocol": {"hivemind_websocket_protocol": '
              '{"port": 5678}},\n "database": {"module": '
              '"hivemind-sqlite-db-plugin"},}')

    def _call(self, tmp, content):
        path = Path(tmp) / "hivemind-core" / "server.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if content is not None:
            path.write_bytes(content.encode())
        with patch("hivemind_core.config.xdg_config_home", return_value=tmp):
            try:
                return path, get_server_config(), None
            except Exception as e:  # noqa: BLE001
                return path, None, e

    def test_trailing_comma_file_is_left_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, cfg, err = self._call(tmp, self.BROKEN)
            self.assertIsInstance(err, ServerConfigError)
            self.assertIn(str(path), err.message)
            self.assertIn("Fix the file or remove it", err.message)
            self.assertEqual(path.read_bytes(), self.BROKEN.encode())

    def test_empty_file_is_corrupt_and_left_alone(self):
        for content in ("", "  \n"):
            with tempfile.TemporaryDirectory() as tmp:
                path, cfg, err = self._call(tmp, content)
                self.assertIsInstance(err, ServerConfigError)
                self.assertEqual(path.read_bytes(), content.encode())

    def test_first_run_creates_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, cfg, err = self._call(tmp, None)
            self.assertIsNone(err)
            self.assertIn("network_protocol", json.loads(path.read_text()))

    def test_missing_network_protocol_is_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, cfg, err = self._call(
                tmp, json.dumps({"min_password_bits": 77}))
            self.assertIsNone(err)
            written = json.loads(path.read_text())
            self.assertIsInstance(written["network_protocol"], dict)
            self.assertEqual(written["min_password_bits"], 77)

    def test_torn_storage_load_does_not_overwrite_valid_file(self):
        valid = json.dumps({"network_protocol": {"x": {"port": 1}},
                            "admin_pass": "kept"})

        class TornLoad(JsonStorageXDG):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.clear()  # the storage read the file while it was empty

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hivemind-core" / "server.json"
            path.parent.mkdir(parents=True)
            path.write_text(valid)
            with patch("hivemind_core.config.xdg_config_home",
                       return_value=tmp), \
                    patch("hivemind_core.config.JsonStorageXDG", TornLoad):
                cfg = get_server_config()
            self.assertEqual(path.read_text(), valid)
            self.assertEqual(cfg["admin_pass"], "kept")

    def test_non_object_file_raises_and_is_left_alone(self):
        for content in ("null", '"text"', "[1, 2]"):
            with tempfile.TemporaryDirectory() as tmp:
                path, cfg, err = self._call(tmp, content)
                self.assertIsInstance(err, ServerConfigError)
                self.assertEqual(path.read_text(), content)

    def test_unreadable_file_is_reported_as_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("hivemind_core.config.load_commented_json",
                       side_effect=PermissionError("denied")):
                path, cfg, err = self._call(tmp, "{}")
            self.assertIsInstance(err, ServerConfigError)
            self.assertIn("cannot be read", err.message)
            self.assertNotIn("not valid JSON", err.message)
