"""Local-network presence wiring on the HiveMind service.

hivemind-core advertises itself on the LAN through the optional
hivemind-presence package (UPnP/SSDP and/or zeroconf mDNS). These tests cover
the wiring: the default config block, graceful no-op when the package is
absent, and the kwargs forwarded to ``LocalPresence``.
"""
import importlib.util
from unittest import mock

import pytest

from hivemind_core import config as cfg
from hivemind_core.service import HiveMindService


def _service():
    # avoid touching a real ClientDatabase at construction, and never let the
    # startup key generation write into the developer's real ~/.config/hivemind
    with mock.patch("hivemind_core.service.ClientDatabase"):
        return HiveMindService(identity=mock.MagicMock())


def test_presence_block_in_default_config():
    p = cfg._DEFAULT["presence"]
    assert p["enabled"] is True
    assert p["zeroconf"] is True
    assert p["upnp"] is False
    # dormant transports without a backend must not be advertised
    assert "beacon" not in p
    assert "ggwave" not in p


def test_start_presence_is_noop_without_package(monkeypatch):
    svc = _service()
    # simulate hivemind_presence not installed
    import builtins
    real_import = builtins.__import__

    def _blocked(name, *a, **k):
        if name == "hivemind_presence":
            raise ImportError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    svc._start_presence()  # must not raise
    assert getattr(svc, "_presence", None) is None
    svc._stop_presence()  # also a no-op


@pytest.mark.skipif(importlib.util.find_spec("hivemind_presence") is None,
                    reason="needs hivemind-presence installed")
def test_start_presence_builds_localpresence_when_available():
    svc = _service()
    with mock.patch("hivemind_presence.LocalPresence") as LP, \
         mock.patch("hivemind_core.service.create_daemon"):
        svc._start_presence()
    assert LP.called


def test_start_presence_forwards_only_upnp_zeroconf():
    """_start_presence must forward exactly the transports hivemind-presence
    supports (upnp/zeroconf) and nothing else."""
    svc = _service()
    captured = {}

    class _LocalPresence:
        def __init__(self, port=5678, ssl=False, name="HiveMind-Node",
                     upnp=False, zeroconf=True):
            captured.update(port=port, ssl=ssl, name=name,
                            upnp=upnp, zeroconf=zeroconf)

        def start(self):
            pass

    import sys
    import types
    fake_mod = types.ModuleType("hivemind_presence")
    fake_mod.LocalPresence = _LocalPresence
    with mock.patch.dict(sys.modules, {"hivemind_presence": fake_mod}), \
         mock.patch("hivemind_core.service.create_daemon"):
        svc._start_presence()
    assert captured["zeroconf"] is True
    assert captured["upnp"] is False
    assert "beacon" not in captured
    assert "ggwave" not in captured


def test_start_presence_disabled_is_noop():
    svc = _service()
    calls = []

    class _LocalPresence:
        def __init__(self, *a, **k):
            calls.append((a, k))

        def start(self):
            pass

    import sys
    import types
    fake_mod = types.ModuleType("hivemind_presence")
    fake_mod.LocalPresence = _LocalPresence
    with mock.patch.dict(sys.modules, {"hivemind_presence": fake_mod}), \
         mock.patch("hivemind_core.service.get_server_config",
                    return_value={"presence": {"enabled": False},
                                  "network_protocol": {}}), \
         mock.patch("hivemind_core.service.create_daemon"):
        svc._start_presence()
    assert calls == []  # LocalPresence never constructed
    assert getattr(svc, "_presence", None) is None
