"""A network transport that is configured but not installed.

hivemind-core's default ``network_protocol`` enables both
``hivemind-websocket-plugin`` and ``hivemind-http-plugin``, but only the
WebSocket transport is a dependency. The HTTP transport ships in the separate
``hivemind-http-protocol`` package (``hivemind-http-plugin`` is only its entry
point name). On a fresh install core wrote both transports into server.json,
and every start then logged ``Failed to load plugin 'hivemind-http-plugin'``
with a full ``KeyError`` traceback that looks like a crash, naming no package
to install (reproduced on the ser9 fresh-install QA rig). The node itself kept
running on the WebSocket transport.

Two fixes are covered:
* at startup, a transport that is not installed is logged as one ERROR line
  that names the transport and the package to install, with no traceback; a
  transport that fails for any other reason still logs its traceback;
* on the first run, server.json enables only the transports that are
  installed. ``_DEFAULT`` is unchanged, and an existing server.json is never
  rewritten.
"""
import json
from unittest import mock

from hivemind_core.service import HiveMindService

# --- startup: loading the configured transports ----------------------------


def _service():
    with mock.patch("hivemind_core.service.ClientDatabase"):
        return HiveMindService(identity=mock.MagicMock())


def _run(monkeypatch, network_protocol, get_class):
    svc = _service()
    log = mock.MagicMock()
    monkeypatch.setattr("hivemind_core.service.LOG", log)
    monkeypatch.setattr("hivemind_core.service.get_agent_protocol",
                        lambda: (lambda config: mock.MagicMock(), {}))
    monkeypatch.setattr("hivemind_core.service.get_binary_protocol",
                        lambda: (lambda **kw: mock.MagicMock(), {}))
    monkeypatch.setattr("hivemind_core.service.get_server_config",
                        lambda: {"network_protocol": network_protocol})
    monkeypatch.setattr("hivemind_core.service.NetworkProtocolFactory.get_class", get_class)
    monkeypatch.setattr("hivemind_core.service.create_daemon", lambda target, args=(): None)
    monkeypatch.setattr("hivemind_core.service.wait_for_exit_signal", lambda: None)
    svc.hm_protocol = mock.MagicMock()
    svc._start_presence = lambda: None
    svc._connect_upstream = lambda hm_protocol: None
    svc._status = mock.MagicMock()
    svc.run()
    return log


def _messages(calls):
    return [" ".join(str(a) for a in c.args) for c in calls]


def _not_installed(name):
    # the exact error hivemind-plugin-manager raises for an unknown entry point
    raise KeyError(f"'{name}' not found. Available plugins: ['hivemind-websocket-plugin']")


def test_a_transport_that_is_not_installed_is_named_without_a_traceback(monkeypatch):
    built = []

    class WebSocket:
        def __init__(self, **kwargs):
            built.append("ws")

        def run(self):
            pass

    def get_class(name):
        if name == "hivemind-http-plugin":
            _not_installed(name)
        return WebSocket

    log = _run(monkeypatch, {"hivemind-websocket-plugin": {}, "hivemind-http-plugin": {}}, get_class)

    assert built == ["ws"], "the installed transport must still start"
    tracebacks = [m for m in _messages(log.exception.call_args_list) if "hivemind-http-plugin" in m]
    assert not tracebacks, f"a missing transport must not log a traceback: {tracebacks}"
    errors = [m for m in _messages(log.error.call_args_list) if "hivemind-http-plugin" in m]
    assert len(errors) == 1, errors
    assert "hivemind-http-protocol" in errors[0], "the log must name the package to install"
    assert "network_protocol" in errors[0], "the log must say where the transport is enabled"


def test_an_unknown_missing_transport_is_still_named(monkeypatch):
    def get_class(name):
        if name == "my-custom-transport":
            _not_installed(name)
        return type("WebSocket", (), {"__init__": lambda self, **kw: None, "run": lambda self: None})

    log = _run(monkeypatch, {"hivemind-websocket-plugin": {}, "my-custom-transport": {}}, get_class)

    errors = [m for m in _messages(log.error.call_args_list) if "my-custom-transport" in m]
    assert len(errors) == 1, errors
    assert not [m for m in _messages(log.exception.call_args_list) if "my-custom-transport" in m]


def test_a_transport_that_fails_to_start_still_logs_its_traceback(monkeypatch):
    class Broken:
        def __init__(self, **kwargs):
            raise RuntimeError("port already in use")

    class WebSocket:
        def __init__(self, **kwargs):
            pass

        def run(self):
            pass

    log = _run(monkeypatch, {"hivemind-websocket-plugin": {}, "broken-transport": {}},
               lambda name: Broken if name == "broken-transport" else WebSocket)

    assert [m for m in _messages(log.exception.call_args_list) if "broken-transport" in m], \
        "an installed transport that fails must keep its traceback"


# --- first run: which transports server.json enables ------------------------

def _fresh_config(tmp_path, monkeypatch, installed):
    from hivemind_core import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "xdg_config_home", lambda: str(tmp_path))
    monkeypatch.setattr(cfg_mod, "find_plugins",
                        lambda plug_type=None: {name: object for name in installed},
                        raising=False)
    return cfg_mod


def test_first_run_enables_only_the_installed_transports(tmp_path, monkeypatch):
    cfg_mod = _fresh_config(tmp_path, monkeypatch, ["hivemind-websocket-plugin"])

    cfg = cfg_mod.get_server_config()

    assert list(cfg["network_protocol"]) == ["hivemind-websocket-plugin"]
    on_disk = json.loads((tmp_path / "hivemind-core" / "server.json").read_text())
    assert list(on_disk["network_protocol"]) == ["hivemind-websocket-plugin"]
    assert "hivemind-http-plugin" in cfg_mod._DEFAULT["network_protocol"], \
        "the documented defaults must not change"


def test_first_run_enables_both_when_both_are_installed(tmp_path, monkeypatch):
    cfg_mod = _fresh_config(tmp_path, monkeypatch,
                            ["hivemind-websocket-plugin", "hivemind-http-plugin"])

    cfg = cfg_mod.get_server_config()

    assert list(cfg["network_protocol"]) == ["hivemind-websocket-plugin", "hivemind-http-plugin"]


def test_an_existing_server_json_is_not_rewritten(tmp_path, monkeypatch):
    cfg_mod = _fresh_config(tmp_path, monkeypatch, ["hivemind-websocket-plugin"])
    path = tmp_path / "hivemind-core" / "server.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"network_protocol": {
        "hivemind-websocket-plugin": {}, "hivemind-http-plugin": {"port": 5679}}}))

    cfg = cfg_mod.get_server_config()

    assert list(cfg["network_protocol"]) == ["hivemind-websocket-plugin", "hivemind-http-plugin"]
