"""Top-level conftest.

Loads hivescope's pytest plugin only when hivescope is importable, so unit/
coverage workflows that don't install hivescope can still run without
loading the e2e fixtures.
"""
try:
    import hivescope  # noqa: F401
    pytest_plugins = ["hivescope.pytest_fixtures"]
except ImportError:
    pass
