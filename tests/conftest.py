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
    """Keep the developer's real config out of the tests.

    ``get_server_config`` reads ``$XDG_CONFIG_HOME/hivemind-core/server.json``.
    On a machine that actually runs a hub that file exists, so tests asserting
    on "the default config" silently read local settings and fail only for the
    person who has a deployment. CI never saw it.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg")))
