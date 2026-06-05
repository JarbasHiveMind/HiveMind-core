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
