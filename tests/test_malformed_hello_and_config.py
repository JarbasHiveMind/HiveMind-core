"""Adversarial regressions for malformed HELLO sessions and non-conforming
server.json blocks.

Each defect used to take the whole node down (or crash the handling of a
single connection) instead of failing gracefully.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ovos_bus_client.session import Session

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_core.config import _DEFAULT, get_server_config, runtime_password_min_bits
from hivemind_core.protocol import HiveMindClientConnection, HiveMindListenerProtocol


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.callbacks = MagicMock()

    db_user = MagicMock()
    db_user.allowed_types = []
    db_user.is_admin = True

    db = MagicMock()
    db.get_client_by_api_key.return_value = db_user

    return HiveMindListenerProtocol(agent_protocol=agent, db=db,
                                    require_crypto=False,
                                    handshake_enabled=False)


def _make_client(protocol):
    client = HiveMindClientConnection(
        key="test-key",
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=protocol,
        sess=Session("a-session"),
    )
    client.name = "test-client"
    client.allowed_types = []
    client.crypto_key = None
    return client


def _sent(client):
    return "".join(str(c.args[0]) for c in client.send_msg.call_args_list)


class TestMalformedHelloSession(unittest.TestCase):
    """A HELLO whose 'session' carrier is not a JSON object must not crash
    the connection handler."""

    def test_non_dict_session_is_rejected_not_crashed(self):
        protocol = _make_protocol()
        client = _make_client(protocol)
        message = HiveMessage(HiveMessageType.HELLO,
                              payload={"session": "not-a-dict"})

        protocol.handle_message(message, client)  # must not raise

        sent = _sent(client)
        self.assertIn("hive.policy.denied", sent)
        self.assertIn("malformed_payload", sent)

    def test_malformed_hello_does_not_kick_the_peer(self):
        protocol = _make_protocol()
        client = _make_client(protocol)

        protocol.handle_message(
            HiveMessage(HiveMessageType.HELLO,
                       payload={"session": "not-a-dict"}), client)

        client.disconnect.assert_not_called()

    def test_a_well_formed_hello_is_untouched(self):
        protocol = _make_protocol()
        client = _make_client(protocol)
        message = HiveMessage(HiveMessageType.HELLO,
                              payload={"session": Session("other-session").serialize()})

        protocol.handle_message(message, client)

        self.assertNotIn("malformed_payload", _sent(client))
        self.assertEqual(client.sess.session_id, "other-session")


class TestNetworkProtocolNonConformingConfig(unittest.TestCase):
    """A hand-edited `network_protocol: null` used to survive the top-level
    backfill untouched and blow up `.items()` at the use site."""

    def _config(self, tmp_path, monkeypatch, written):
        from hivemind_core import config as cfg_mod
        cfgdir = tmp_path / "hivemind-core"
        cfgdir.mkdir(parents=True)
        (cfgdir / "server.json").write_text(json.dumps(written))
        monkeypatch.setattr(cfg_mod, "xdg_config_home", lambda: str(tmp_path))
        return cfg_mod.get_server_config()

    def test_null_network_protocol_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hivemind-core" / "server.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"network_protocol": None}))
            with patch("hivemind_core.config.xdg_config_home",
                       return_value=tmp):
                cfg = get_server_config()
            self.assertIsInstance(cfg["network_protocol"], dict)
            self.assertEqual(cfg["network_protocol"].items(),
                             _DEFAULT["network_protocol"].items())

    def test_string_network_protocol_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hivemind-core" / "server.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"network_protocol": "garbage"}))
            with patch("hivemind_core.config.xdg_config_home",
                       return_value=tmp):
                cfg = get_server_config()
            self.assertIsInstance(cfg["network_protocol"], dict)


class TestMinPasswordBitsNonConformingConfig(unittest.TestCase):
    """A hand-edited `min_password_bits` that is not a number used to raise
    ValueError/TypeError out of `runtime_password_min_bits`, taking the
    handshake path down for every client."""

    def test_non_numeric_min_password_bits_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hivemind-core" / "server.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"min_password_bits": "very-strong"}))
            with patch("hivemind_core.config.xdg_config_home",
                       return_value=tmp), \
                 patch.dict("os.environ", {}, clear=False):
                import os
                os.environ.pop("HIVEMIND_DISABLE_PASSWORD_STRENGTH_CHECK", None)
                bits = runtime_password_min_bits()
            self.assertEqual(bits, float(_DEFAULT["min_password_bits"]))


if __name__ == "__main__":
    unittest.main()
