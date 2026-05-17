import pytest
from click import BadParameter

import hivemind_core.database as db_module
from hivemind_core.database import (
    CLIENT_SUPPORTS_METADATA,
    ClientDatabase,
    METADATA_SUPPORT_REQUIRED,
)
from hivemind_core.scripts import parse_client_metadata


class MemoryDB:
    def __init__(self):
        self.clients = []

    def search_by_value(self, key, value):
        return [client for client in self.clients if getattr(client, key) == value]

    def add_item(self, client):
        self.clients.append(client)
        return True

    def update_item(self, client):
        return True

    def __len__(self):
        return len(self.clients)


def make_client_db():
    db = object.__new__(ClientDatabase)
    db.db = MemoryDB()
    return db


def test_parse_client_metadata_allows_json_object():
    assert parse_client_metadata('{"account_id":"acct_123"}') == {
        "account_id": "acct_123",
    }


def test_parse_client_metadata_allows_omitted_value():
    assert parse_client_metadata(None) is None


def test_parse_client_metadata_rejects_empty_value():
    with pytest.raises(BadParameter):
        parse_client_metadata("")


def test_parse_client_metadata_rejects_invalid_json():
    with pytest.raises(BadParameter):
        parse_client_metadata("{")


def test_parse_client_metadata_rejects_non_object():
    with pytest.raises(BadParameter):
        parse_client_metadata('["account_id"]')


def test_add_client_rejects_metadata_when_not_supported(monkeypatch):
    monkeypatch.setattr(db_module, "CLIENT_SUPPORTS_METADATA", False)
    db = make_client_db()

    with pytest.raises(RuntimeError) as exc:
        db.add_client(name="satellite", key="access-key", metadata={"k": "v"})

    assert str(exc.value) == METADATA_SUPPORT_REQUIRED


def test_client_supports_metadata_falls_back_to_annotations(monkeypatch):
    class ClientWithMetadata:
        __annotations__ = {"metadata": dict}

    def fail_fields(_client):
        raise TypeError

    monkeypatch.setattr(db_module, "Client", ClientWithMetadata)
    monkeypatch.setattr(db_module, "fields", fail_fields)

    assert db_module._client_supports_metadata()


@pytest.mark.skipif(not CLIENT_SUPPORTS_METADATA, reason=METADATA_SUPPORT_REQUIRED)
def test_add_client_preserves_metadata():
    db = make_client_db()

    assert db.add_client(
        name="satellite",
        key="access-key",
        metadata={"account_id": "acct_123"},
    )

    client = db.get_client_by_api_key("access-key")
    assert client.metadata == {"account_id": "acct_123"}


@pytest.mark.skipif(not CLIENT_SUPPORTS_METADATA, reason=METADATA_SUPPORT_REQUIRED)
def test_add_client_updates_existing_metadata():
    db = make_client_db()
    db.add_client(
        name="satellite",
        key="access-key",
        metadata={"account_id": "acct_123"},
    )

    assert db.add_client(
        name="satellite",
        key="access-key",
        metadata={"account_id": "acct_456", "group": "standard"},
    )

    client = db.get_client_by_api_key("access-key")
    assert client.metadata == {"account_id": "acct_456", "group": "standard"}
