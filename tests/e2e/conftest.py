"""Shared fixtures for the e2e suite.

The e2e tests spin up real masters and clients in-process; both sides
persist state under the XDG config home (node identity file, RSA .pem
files, Noise static keys and TOFU key pins). Redirect XDG to a per-test
temporary directory so tests never read from or write to the developer's
real ``~/.config/hivemind`` and every test starts from a clean identity
(no stale key pins leaking between tests).
"""

import pytest


@pytest.fixture(autouse=True)
def isolated_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return tmp_path
