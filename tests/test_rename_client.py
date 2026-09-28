"""`rename-client` must not destroy a name it was never given.

`--name` was optional and assigned unconditionally, so `rename-client 1` with
no name blanked the client's friendly name and printed "Renamed 'kitchen' to
None" — a destructive edit reported as a success, with the old value
unrecoverable.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from hivemind_core.scripts import rename_client


class _DB:
    def __init__(self, client):
        self.client = client
        self.updated = []

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def update_item(self, client):
        self.updated.append(client)


def _client(**kw):
    return SimpleNamespace(name="kitchen", client_id=1,
                           api_key="c0d14821bbece410349e2541", **kw)


def _run(db, client, *args):
    with patch("hivemind_core.scripts.ClientDatabase", return_value=db), \
            patch("hivemind_core.scripts.resolve_client", return_value=client):
        return CliRunner().invoke(rename_client, list(args))


def test_a_missing_name_is_refused_and_changes_nothing():
    client = _client()
    db = _DB(client)

    result = _run(db, client, "1")

    assert result.exit_code != 0, result.output
    assert client.name == "kitchen", "the old name must survive"
    assert db.updated == [], "nothing may be written"


def test_a_name_is_applied():
    client = _client()
    db = _DB(client)

    result = _run(db, client, "1", "--name", "living-room")

    assert result.exit_code == 0, result.output
    assert client.name == "living-room"
    assert db.updated == [client]


def test_the_access_key_the_logs_print_is_accepted():
    """The node names clients by access key; coercing to int rejected that
    value before resolve_client ever saw it."""
    client = _client()
    db = _DB(client)

    result = _run(db, client, "c0d14821bbece410349e2541", "--name", "hall")

    assert result.exit_code == 0, result.output
    assert "not a valid integer" not in result.output
    assert client.name == "hall"


def test_an_unknown_node_is_reported_and_writes_nothing():
    db = _DB(None)

    result = _run(db, None, "99", "--name", "whatever")

    assert "Invalid Node ID" in result.output
    assert db.updated == []
