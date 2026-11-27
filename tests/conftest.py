import pytest
"""Shared pytest hooks for the hivemind-core test suite."""


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Warn loudly when an xfail-marked test starts passing.

    Conformance/feature-gap tests are marked ``@pytest.mark.xfail`` (executable
    TODOs tied to the implementing PR). When the feature lands the test XPASSes;
    this surfaces it so the marker gets flipped to a real assertion instead of
    silently rotting as a permanent xfail.
    """
    xpassed = terminalreporter.stats.get("xpassed", [])
    if not xpassed:
        return
    terminalreporter.write_sep("=", "XPASS — flip these xfail markers", yellow=True, bold=True)
    terminalreporter.write_line(
        f"{len(xpassed)} xfail-marked test(s) now PASS — a feature marked "
        "unimplemented appears to work. Remove the @pytest.mark.xfail and turn "
        "it into a real check:"
    )
    for rep in xpassed:
        terminalreporter.write_line(f"  XPASS  {rep.nodeid}")


@pytest.fixture(autouse=True)
def _isolate_xdg_config(tmp_path_factory, monkeypatch):
    """Keep the developer's real config and data out of the tests.

    ``get_server_config`` reads ``$XDG_CONFIG_HOME/hivemind-core/server.json``.
    On a machine that actually runs a hub that file exists, so tests asserting
    on "the default config" silently read local settings and fail only for the
    person who has a deployment. CI never saw it.

    ``$XDG_DATA_HOME`` is the same story with teeth: it holds
    ``hivemind-core/clients.db``. A test that patches
    ``hivemind_core.config.xdg_data_home`` does not move the database, because
    the database plugin imports ``xdg_data_home`` from ``ovos_utils.xdg_utils``
    into its own namespace and resolves the real path. So the CLI tests read
    and WRITE the developer's own client rows, and
    ``test_add_client_refuses_to_overwrite_existing_access_key`` fails on a box
    whose database already holds its fixture key — on any branch, including an
    unmodified dev.

    The environment variable is what every consumer reads, whatever it
    imported, so it is set here rather than patched per module.
    """
    xdg = tmp_path_factory.mktemp("xdg")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(xdg / "cache"))


class _InlineExecutor:
    """Runs a submitted job on the calling thread, so a unit test that stubs
    the answering backend sees its escalation before the handler returns."""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)

    def shutdown(self, wait=True, cancel_futures=False):
        pass


@pytest.fixture(autouse=True)
def _answer_queries_inline(request, monkeypatch):
    """QUERY/CASCADE answers run on a worker thread in production. Unit tests
    assert on the handler's effects right after it returns, so they get an
    inline executor. The end-to-end tests and the off-loop tests keep the real
    pool."""
    if "e2e" in request.node.path.parts or "off_loop" in request.node.path.name:
        return
    from hivemind_core.protocol import HiveMindListenerProtocol
    monkeypatch.setattr(HiveMindListenerProtocol, "_query_executor",
                        _InlineExecutor())
