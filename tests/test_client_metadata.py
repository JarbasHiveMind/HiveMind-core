from unittest.mock import patch

import pytest
from click import BadParameter
from click.testing import CliRunner

from hivemind_core.database import ClientDatabase
from hivemind_core.scripts import add_client, parse_client_metadata


class MemoryDB:
    """Minimal AbstractDB stand-in for ClientDatabase tests."""

    def __init__(self):
        self.clients = []

    def search_by_value(self, key, value):
        return [c for c in self.clients if getattr(c, key, None) == value]

    def add_item(self, client):
        self.clients.append(client)
        return True

    def update_item(self, client):
        for i, c in enumerate(self.clients):
            if c.client_id == client.client_id:
                self.clients[i] = client
                return True
        self.clients.append(client)
        return True

    def __len__(self):
        return len(self.clients)

    def __iter__(self):
        return iter(self.clients)


def make_client_db():
    db = object.__new__(ClientDatabase)
    db.db = MemoryDB()
    return db


# --- parse_client_metadata ---------------------------------------------------


def test_parse_metadata_accepts_json_object():
    assert parse_client_metadata('{"account_id":"acct_123"}') == {
        "account_id": "acct_123",
    }


def test_parse_metadata_accepts_empty_object():
    assert parse_client_metadata("{}") == {}


def test_parse_metadata_passes_through_none():
    assert parse_client_metadata(None) is None


def test_parse_metadata_rejects_empty_string():
    with pytest.raises(BadParameter):
        parse_client_metadata("")


def test_parse_metadata_rejects_malformed_json():
    with pytest.raises(BadParameter):
        parse_client_metadata("{")


def test_parse_metadata_rejects_top_level_array():
    with pytest.raises(BadParameter):
        parse_client_metadata('["account_id"]')


def test_parse_metadata_rejects_top_level_string():
    with pytest.raises(BadParameter):
        parse_client_metadata('"just-a-string"')


def test_parse_metadata_rejects_top_level_number():
    with pytest.raises(BadParameter):
        parse_client_metadata("42")


def test_parse_metadata_accepts_nested_structures():
    payload = '{"tags":["a","b"],"flags":{"premium":true}}'
    assert parse_client_metadata(payload) == {
        "tags": ["a", "b"],
        "flags": {"premium": True},
    }


# --- ClientDatabase.add_client metadata round-trip --------------------------


def test_add_client_persists_metadata():
    db = make_client_db()
    assert db.add_client(
        name="satellite",
        key="access-key",
        metadata={"account_id": "acct_123"},
    )
    client = db.get_client_by_api_key("access-key")
    assert client.metadata == {"account_id": "acct_123"}


def test_add_client_defaults_metadata_to_empty_dict():
    db = make_client_db()
    assert db.add_client(name="satellite", key="access-key")
    client = db.get_client_by_api_key("access-key")
    assert client.metadata == {}


def test_add_client_overwrites_metadata_on_existing_client():
    db = make_client_db()
    db.add_client(name="satellite", key="access-key", metadata={"account_id": "acct_123"})
    assert db.add_client(
        name="satellite",
        key="access-key",
        metadata={"account_id": "acct_456", "group": "standard"},
    )
    client = db.get_client_by_api_key("access-key")
    assert client.metadata == {"account_id": "acct_456", "group": "standard"}


def test_add_client_leaves_metadata_alone_when_not_provided_on_update():
    db = make_client_db()
    db.add_client(name="satellite", key="access-key", metadata={"account_id": "acct_123"})
    db.add_client(name="satellite-renamed", key="access-key")
    client = db.get_client_by_api_key("access-key")
    assert client.metadata == {"account_id": "acct_123"}
    assert client.name == "satellite-renamed"


def test_add_client_copies_metadata_dict():
    db = make_client_db()
    payload = {"account_id": "acct_123"}
    db.add_client(name="satellite", key="access-key", metadata=payload)
    payload["account_id"] = "mutated"
    client = db.get_client_by_api_key("access-key")
    assert client.metadata == {"account_id": "acct_123"}


# --- CLI end-to-end ----------------------------------------------------------


def _patched_db_ctx(fake_db):
    class _Ctx:
        def __enter__(self): return fake_db
        def __exit__(self, *a): return False
    return _Ctx()


def test_cli_add_client_with_metadata_flows_to_db():
    runner = CliRunner()
    fake_db = make_client_db()

    with patch("hivemind_core.scripts.ClientDatabase", return_value=_patched_db_ctx(fake_db)):
        result = runner.invoke(
            add_client,
            [
                "--name", "satellite",
                "--access-key", "access-key",
                "--password", "pw",
                "--metadata", '{"account_id":"acct_123"}',
            ],
        )

    assert result.exit_code == 0, result.output
    client = fake_db.get_client_by_api_key("access-key")
    assert client.metadata == {"account_id": "acct_123"}
    assert "Metadata:" in result.output
    assert '"account_id": "acct_123"' in result.output


def test_cli_add_client_rejects_invalid_metadata_json():
    runner = CliRunner()
    result = runner.invoke(
        add_client,
        ["--name", "satellite", "--access-key", "k", "--password", "pw", "--metadata", "{"],
    )
    assert result.exit_code != 0
    assert "must be valid JSON" in result.output


def test_cli_add_client_rejects_metadata_top_level_array():
    runner = CliRunner()
    result = runner.invoke(
        add_client,
        ["--name", "satellite", "--access-key", "k", "--password", "pw", "--metadata", "[]"],
    )
    assert result.exit_code != 0
    assert "must be a JSON object" in result.output


def test_cli_add_client_without_metadata_omits_metadata_line():
    runner = CliRunner()
    fake_db = make_client_db()

    with patch("hivemind_core.scripts.ClientDatabase", return_value=_patched_db_ctx(fake_db)):
        result = runner.invoke(
            add_client,
            ["--name", "satellite", "--access-key", "k", "--password", "pw"],
        )

    assert result.exit_code == 0, result.output
    assert "Metadata:" not in result.output
