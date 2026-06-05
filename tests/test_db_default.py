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


def test_sqlite_wins_once_present():
    with mock.patch.object(C, "xdg_data_home", return_value=_make_existing(json=True, sqlite=True)):
        assert C._default_database()["module"] == "hivemind-sqlite-db-plugin"


@pytest.mark.skipif(
    not _sqlite_supports_current_client_model(),
    reason="needs hivemind-sqlite-database>=0.3.0a1 (current Client model)")
def test_migrate_db_copies_clients_json_to_sqlite():
    tmp_json = tempfile.mkdtemp()
    tmp_sqlite = tempfile.mkdtemp()
    cfgj = {"module": "hivemind-json-db-plugin",
            "hivemind-json-db-plugin": {"name": "clients", "subfolder": "hivemind-core"}}
    # seed a JSON db with a client (commit the store explicitly)
    with mock.patch("hivemind_json_database.xdg_data_home", return_value=tmp_json):
        from hivemind_json_database import JsonDB
        jdb = ClientDatabase(config=cfgj)
        jdb.db = JsonDB(name="clients", subfolder="hivemind-core")
        jdb.db._db.store()
        jdb.add_client(name="sat", key="K1", password="pw",
                       allowed_types=["recognizer_loop:utterance"],
                       metadata={"skill_blacklist": ["skill-weather"]})
        jdb.db._db.store()

    runner = CliRunner()
    with mock.patch("hivemind_json_database.xdg_data_home", return_value=tmp_json), \
         mock.patch("hivemind_sqlite_database.xdg_data_home", return_value=tmp_sqlite):
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
