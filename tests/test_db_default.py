"""Default client-database backend selection + cross-backend migration."""
import os
import tempfile
from unittest import mock

import pytest
from click.testing import CliRunner

from hivemind_core import config as C
from hivemind_core.database import ClientDatabase
from hivemind_core.scripts import migrate_db


def _sqlite_supports_current_client_model() -> bool:
    """The published sqlite plugin < 0.3.0a1 references the removed
    Client.message_blacklist field in add_item; skip the migration test
    until that schema-v2 build (HiveMind-sqlite-database#32) is released."""
    try:
        import importlib.metadata as _m
        from packaging.version import Version
        return Version(_m.version("hivemind-sqlite-database")) >= Version("0.3.0a1")
    except Exception:
        return False


def _make_existing(json=False, sqlite=False):
    tmp = tempfile.mkdtemp()
    base = os.path.join(tmp, "hivemind-core")
    os.makedirs(base, exist_ok=True)
    if json:
        open(os.path.join(base, "clients.json"), "w").write("{}")
    if sqlite:
        open(os.path.join(base, "clients.db"), "w").write("")
    return tmp


def test_fresh_install_defaults_to_sqlite():
    with mock.patch.object(C, "xdg_data_home", return_value=tempfile.mkdtemp()):
        assert C._default_database()["module"] == "hivemind-sqlite-db-plugin"


def test_existing_json_deployment_is_kept():
    with mock.patch.object(C, "xdg_data_home", return_value=_make_existing(json=True)):
        assert C._default_database()["module"] == "hivemind-json-db-plugin"


def test_client_database_delegates_client_refresh():
    backend = mock.Mock()
    backend.get_client_by_id.return_value = "by-id"
    backend.refresh.return_value = "fresh"

    db = object.__new__(ClientDatabase)
    db.db = backend

    assert db.get_client_by_id(7) == "by-id"
    assert db.refresh(7) == "fresh"
    backend.get_client_by_id.assert_called_once_with(7)
    backend.refresh.assert_called_once_with(7)


def test_sqlite_wins_once_present():
    with mock.patch.object(C, "xdg_data_home", return_value=_make_existing(json=True, sqlite=True)):
        assert C._default_database()["module"] == "hivemind-sqlite-db-plugin"


@pytest.mark.skipif(
    not _sqlite_supports_current_client_model(),
    reason="needs hivemind-sqlite-database>=0.3.0a1 (current Client model)")
def test_migrate_db_copies_clients_json_to_sqlite():
    from hivemind_plugin_manager import DatabaseFactory

    tmp_json = tempfile.mkdtemp()
    tmp_sqlite = tempfile.mkdtemp()
    cfgj = {"module": "hivemind-json-db-plugin",
            "hivemind-json-db-plugin": {"name": "clients", "subfolder": "hivemind-core"}}
    # The json plugin entry-point is currently provided by json-database's
    # bundled `json_database.hpm:JsonDB`, NOT by the standalone
    # `hivemind_json_database` package (both register the same
    # `hivemind-json-db-plugin` name). migrate_db / ClientDatabase load
    # whatever the factory resolves, so we must patch xdg on *that* module —
    # otherwise the CLI reads the real ~/.local/share store and migrates 0
    # clients. Resolve the live module dynamically so this keeps working
    # whichever package wins the entry-point.
    json_mod = DatabaseFactory.get_class("hivemind-json-db-plugin").__module__
    sqlite_mod = DatabaseFactory.get_class("hivemind-sqlite-db-plugin").__module__

    # seed a JSON db with a client via the supported add_client path
    with mock.patch(f"{json_mod}.xdg_data_home", return_value=tmp_json):
        jdb = ClientDatabase(config=cfgj)
        jdb.add_client(name="sat", key="K1", password="pw",
                       allowed_types=["recognizer_loop:utterance"],
                       metadata={"skill_blacklist": ["skill-weather"]})
        jdb.db._db.store()

    runner = CliRunner()
    with mock.patch(f"{json_mod}.xdg_data_home", return_value=tmp_json), \
         mock.patch(f"{sqlite_mod}.xdg_data_home", return_value=tmp_sqlite):
        result = runner.invoke(migrate_db, ["--from", "hivemind-json-db-plugin",
                                            "--to", "hivemind-sqlite-db-plugin"])
        assert result.exit_code == 0, result.output
        assert "Migrated 1 client" in result.output
        sdb = ClientDatabase(config={"module": "hivemind-sqlite-db-plugin",
                                     "hivemind-sqlite-db-plugin": {"name": "clients", "subfolder": "hivemind-core"}})
        got = sdb.get_client_by_api_key("K1")
        assert got is not None
        assert got.metadata.get("skill_blacklist") == ["skill-weather"]


def test_migrate_db_rejects_same_backend():
    runner = CliRunner()
    result = runner.invoke(migrate_db, ["--from", "x", "--to", "x"])
    assert result.exit_code != 0
