"""Shared fixtures for the e2e suite.

The e2e tests spin up real masters and clients in-process; both sides
persist state under the XDG config home (node identity file, RSA .pem
files, Noise static keys and TOFU key pins). Redirect XDG to a per-test
temporary directory so tests never read from or write to the developer's
real ``~/.config/hivemind`` and every test starts from a clean identity
(no stale key pins leaking between tests).
"""

import json

import pytest

import hivemind_bus_client.identity as _identity_module
import poorman_handshake.symmetric as _pm_symmetric
from json_database import JsonConfigXDG as _JsonConfigXDG


@pytest.fixture(autouse=True)
def isolated_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    # JsonConfigXDG binds its default xdg_folder when json_database is
    # imported, before this fixture can change the environment. Patch the
    # constructor used by NodeIdentity so every test identity is guaranteed
    # to live below tmp_path even when the module was imported during pytest
    # collection. Without this, an e2e client can overwrite a developer's
    # real ~/.config/hivemind/_identity.json.
    identity_config_root = tmp_path / "config"

    def isolated_identity_config(name, *args, **kwargs):
        kwargs["xdg_folder"] = identity_config_root
        return _JsonConfigXDG(name, *args, **kwargs)

    monkeypatch.setattr(
        _identity_module, "JsonConfigXDG", isolated_identity_config
    )

    # The suite uses short human-readable passwords ("matrix-pwd", ...) that
    # poorman-handshake's strength backstop would refuse. Disable the runtime
    # check via the documented env var (honoured by the hivemind client/server
    # handshake construction) and neutralise the library-level check for any
    # component that builds a PasswordHandShake without threading min_bits
    # through (e.g. the hivescope test harness).
    monkeypatch.setenv("HIVEMIND_DISABLE_PASSWORD_STRENGTH_CHECK", "1")
    monkeypatch.setattr(_pm_symmetric, "check_password_strength",
                        lambda *args, **kwargs: None)

    # Non-Noise connections top out at protocol v1, so the legacy-fallback
    # matrix rows need the server's protocol floor below the production
    # default (min_protocol_version=2). Only this isolated test config is
    # lowered; the shipped default is unchanged.
    server_cfg_dir = tmp_path / "config" / "hivemind-core"
    server_cfg_dir.mkdir(parents=True, exist_ok=True)
    (server_cfg_dir / "server.json").write_text(
        json.dumps({"min_protocol_version": 0}))
    return tmp_path
