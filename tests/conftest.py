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
