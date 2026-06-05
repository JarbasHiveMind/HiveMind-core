"""Local-network presence + GGWave pairing wiring on the HiveMind service."""
import importlib.util
from unittest import mock

import pytest

from hivemind_core import config as cfg
from hivemind_core.service import HiveMindService


def _service():
    # avoid touching a real ClientDatabase at construction
    with mock.patch("hivemind_core.service.ClientDatabase"):
        return HiveMindService()


def test_presence_block_in_default_config():
    with mock.patch.object(cfg, "xdg_config_home", return_value="/tmp/hm-presence-cfg-xxx"):
        # _DEFAULT carries the presence block; assert the shape
        assert "presence" in cfg._DEFAULT
        p = cfg._DEFAULT["presence"]
        assert p["beacon"] is True and p["ggwave"] is False and p["enabled"] is True


def test_ggwave_add_client_registers_with_generated_crypto():
    svc = _service()
    fake_db = mock.MagicMock()
    fake_db.total_clients.return_value = 0
    ctx = mock.MagicMock()
    ctx.__enter__.return_value = fake_db
    with mock.patch("hivemind_core.service.ClientDatabase", return_value=ctx):
        svc._ggwave_add_client("ACCESS123", "pairing-pw")
    args, kwargs = fake_db.add_client.call_args
    assert "ACCESS123" in args
    assert kwargs.get("password") == "pairing-pw"
    # a 32-hex (AES-256) crypto key is generated for the paired client
    assert len(kwargs.get("crypto_key", "")) == 32


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


def test_start_presence_omits_unsupported_kwargs():
    """Against a LocalPresence that exposes only upnp/zeroconf (today's published
    hivemind-presence), _start_presence must NOT pass beacon/ggwave — else it
    TypeErrors at startup."""
    svc = _service()

    class _OldLocalPresence:  # signature without beacon/ggwave
        def __init__(self, port=5678, ssl=False, service_type="_hivemind._tcp.local.",
                     name="HiveMind-Node", upnp=False, zeroconf=True):
            self.kwargs = dict(port=port, ssl=ssl, name=name, upnp=upnp, zeroconf=zeroconf)

        def start(self):
            pass

    import sys
    import types
    fake_mod = types.ModuleType("hivemind_presence")
    fake_mod.LocalPresence = _OldLocalPresence
    with mock.patch.dict(sys.modules, {"hivemind_presence": fake_mod}), \
         mock.patch("hivemind_core.service.create_daemon"):
        svc._start_presence()  # must not raise
    assert "beacon" not in svc._presence.kwargs
    assert "ggwave" not in svc._presence.kwargs


def test_start_presence_passes_beacon_ggwave_when_supported():
    """Against a future LocalPresence that accepts beacon/ggwave, _start_presence
    forwards them."""
    svc = _service()
    captured = {}

    class _NewLocalPresence:
        def __init__(self, port=5678, ssl=False, name="HiveMind-Node", upnp=False,
                     zeroconf=True, beacon=True, ggwave=False,
                     ggwave_add_client_callback=None):
            captured.update(beacon=beacon, ggwave=ggwave,
                            has_cb=ggwave_add_client_callback is not None)

        def start(self):
            pass

    import sys
    import types
    fake_mod = types.ModuleType("hivemind_presence")
    fake_mod.LocalPresence = _NewLocalPresence
    with mock.patch.dict(sys.modules, {"hivemind_presence": fake_mod}), \
         mock.patch("hivemind_core.service.create_daemon"):
        svc._start_presence()
    assert captured.get("beacon") is True  # default beacon on when supported
