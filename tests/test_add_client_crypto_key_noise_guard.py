"""``add-client --crypto-key`` sets a LEGACY v1/v2 AES pre-shared key. On a
node whose ``min_protocol_version`` requires the v3 Noise handshake (the
default), that key is never used for decryption — the client keeps
encrypting with it, the server's Noise session can't decrypt the result, and
the client surfaces that as a misleading "invalid access key/password" error
instead of the real cause. ``add-client`` used to only print a soft
deprecation warning and proceed; it must refuse instead, with an explicit
``--allow-legacy-crypto-key`` escape hatch for operators who genuinely run
v1/v2 clients on a node that permits them.

Isolation note: ``ClientDatabase`` resolves its sqlite path via
``hivemind_sqlite_database``, which imported ``xdg_data_home`` directly from
``ovos_utils.xdg_utils`` — patching only ``hivemind_core.config.xdg_data_home``
(as tests/test_add_client_no_clobber.py does) leaves that reference live and
the client lands in the real ``~/.local/share`` database. Both import sites
are patched here so these tests never touch the real db.
"""
import json
import os
import tempfile
from unittest import mock

from click.testing import CliRunner

from hivemind_core import config as C
from hivemind_core.database import ClientDatabase
from hivemind_core.scripts import add_client

import hivemind_sqlite_database as _sqlite_plugin


def _isolated_xdg(data_tmp, cfg_tmp):
    return (
        mock.patch.object(C, "xdg_data_home", return_value=data_tmp),
        mock.patch.object(C, "xdg_config_home", return_value=cfg_tmp),
        mock.patch.object(_sqlite_plugin, "xdg_data_home", return_value=data_tmp),
    )


def _seed_server_config(cfg_tmp, config):
    cfg_dir = os.path.join(cfg_tmp, "hivemind-core")
    os.makedirs(cfg_dir, exist_ok=True)
    with open(os.path.join(cfg_dir, "server.json"), "w") as f:
        json.dump(config, f)


def test_crypto_key_refused_on_node_requiring_noise_handshake():
    """FAIL-BEFORE: today this succeeds with only a soft warning and creates
    a client whose crypto_key will silently break every message it sends."""
    data_tmp, cfg_tmp = tempfile.mkdtemp(), tempfile.mkdtemp()
    p1, p2, p3 = _isolated_xdg(data_tmp, cfg_tmp)  # min_protocol_version defaults to 2
    with p1, p2, p3:
        runner = CliRunner()
        result = runner.invoke(add_client, [
            "--access-key", "legacy-refused-0001",
            "--crypto-key", "0123456789abcdef",
        ])
        assert result.exit_code != 0, result.output
        assert "Noise handshake" in result.output
        assert "--allow-legacy-crypto-key" in result.output

        db = ClientDatabase()
        assert db.get_client_by_api_key("legacy-refused-0001") is None, \
            "refused add-client must not create the client"


def test_crypto_key_allowed_with_escape_hatch_on_node_requiring_noise_handshake():
    data_tmp, cfg_tmp = tempfile.mkdtemp(), tempfile.mkdtemp()
    p1, p2, p3 = _isolated_xdg(data_tmp, cfg_tmp)
    with p1, p2, p3:
        runner = CliRunner()
        result = runner.invoke(add_client, [
            "--access-key", "legacy-allowed-0002",
            "--crypto-key", "0123456789abcdef",
            "--allow-legacy-crypto-key",
        ])
        assert result.exit_code == 0, result.output
        assert "deprecated" in result.output

        db = ClientDatabase()
        client = db.get_client_by_api_key("legacy-allowed-0002")
        assert client is not None
        assert client.crypto_key == "0123456789abcdef"


def test_crypto_key_allowed_on_node_permitting_legacy_clients():
    data_tmp, cfg_tmp = tempfile.mkdtemp(), tempfile.mkdtemp()
    _seed_server_config(cfg_tmp, {"min_protocol_version": 0})
    p1, p2, p3 = _isolated_xdg(data_tmp, cfg_tmp)
    with p1, p2, p3:
        runner = CliRunner()
        result = runner.invoke(add_client, [
            "--access-key", "legacy-permitted-0003",
            "--crypto-key", "0123456789abcdef",
        ])
        assert result.exit_code == 0, result.output
        assert "deprecated" in result.output

        db = ClientDatabase()
        client = db.get_client_by_api_key("legacy-permitted-0003")
        assert client is not None
        assert client.crypto_key == "0123456789abcdef"


def test_add_client_without_crypto_key_still_works():
    data_tmp, cfg_tmp = tempfile.mkdtemp(), tempfile.mkdtemp()
    p1, p2, p3 = _isolated_xdg(data_tmp, cfg_tmp)
    with p1, p2, p3:
        runner = CliRunner()
        result = runner.invoke(add_client, ["--access-key", "no-crypto-key-0004"])
        assert result.exit_code == 0, result.output
        assert "Credentials added to database!" in result.output

        db = ClientDatabase()
        assert db.get_client_by_api_key("no-crypto-key-0004") is not None
