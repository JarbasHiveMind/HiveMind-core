"""The suite must not read or write the developer's own XDG directories.

``test_add_client_no_clobber`` failed on this box for months of branches for a
reason none of them caused: the CLI writes ``clients.db`` under the real
``$XDG_DATA_HOME`` because the database plugin imports ``xdg_data_home`` from
``ovos_utils.xdg_utils`` into its own namespace, so patching
``hivemind_core.config.xdg_data_home`` moves nothing. A developer whose
database happens to be empty sees green; anyone who has ever run a hub sees
red.
"""
import os
from pathlib import Path

from ovos_utils.xdg_utils import (xdg_cache_home, xdg_config_home,
                                  xdg_data_home, xdg_state_home)

from hivemind_core import config as C


def _real_home_dirs():
    home = Path.home()
    return (home / ".local" / "share", home / ".config",
            home / ".local" / "state", home / ".cache")


def test_every_xdg_directory_points_somewhere_temporary():
    real_data, real_config, real_state, real_cache = _real_home_dirs()
    assert Path(xdg_data_home()) != real_data
    assert Path(xdg_config_home()) != real_config
    assert Path(xdg_state_home()) != real_state
    assert Path(xdg_cache_home()) != real_cache


def test_the_database_plugin_resolves_the_isolated_path():
    """The plugin reads the environment, not hivemind_core.config."""
    from hivemind_sqlite_database import SQLiteDB

    real_data, _, _, _ = _real_home_dirs()
    db = SQLiteDB()
    assert not db._db_path.startswith(str(real_data)), (
        f"the suite would write the developer's own clients.db: {db._db_path}")
    assert db._db_path.startswith(str(xdg_data_home()))


def test_the_default_backend_is_chosen_from_the_isolated_directory():
    """``_default_database`` picks JSON or SQLite by looking for files on disk.

    Reading the developer's directory makes the answer depend on whose machine
    it is.
    """
    real_data, _, _, _ = _real_home_dirs()
    chosen = C._default_database()
    assert chosen["module"] == "hivemind-sqlite-db-plugin", (
        "an empty data directory must choose SQLite; this read "
        f"{xdg_data_home()}")
    assert not str(xdg_data_home()).startswith(str(real_data))


def test_the_environment_variables_are_set_for_child_processes():
    """A subprocess or a lazily imported module must see the same isolation."""
    for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME",
                "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        assert os.environ.get(var), f"{var} is not set for this test"
        assert str(Path.home() / ".local") not in os.environ[var] or "pytest" in os.environ[var]
