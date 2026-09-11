"""reset-noise-pin — the recovery path for a client that lost its Noise key.

CRYPTO-1 §3.4.5 pins a client's static key on first use and the node then
refuses any v3 handshake presenting a different one. That is the right default
and it is also a total lockout for a satellite that was reinstalled, reflashed
or moved to new hardware: the key legitimately changed, and until this command
existed the only way back was editing the client database by hand.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from hivemind_core.scripts import reset_noise_pin


class _DB:
    """Stands in for ClientDatabase as a context manager."""

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
    return SimpleNamespace(name="sat0", client_id=1, api_key="key-0", **kw)


def _run(db, client, node_id="1"):
    with patch("hivemind_core.scripts.ClientDatabase", return_value=db), \
            patch("hivemind_core.scripts.resolve_client", return_value=client):
        return CliRunner().invoke(reset_noise_pin, [node_id])


def test_a_pinned_key_is_forgotten():
    client = _client(metadata={"noise_pubkey": "abc123", "other": "kept"})
    db = _DB(client)

    result = _run(db, client)

    assert result.exit_code == 0
    assert "noise_pubkey" not in client.metadata
    assert db.updated == [client], "the cleared pin must be persisted"


def test_unrelated_metadata_survives():
    client = _client(metadata={"noise_pubkey": "abc123", "site": "kitchen"})

    _run(_DB(client), client)

    assert client.metadata["site"] == "kitchen"


def test_a_client_with_no_pin_is_left_alone():
    client = _client(metadata={"site": "kitchen"})
    db = _DB(client)

    result = _run(db, client)

    assert "nothing to reset" in result.output
    assert db.updated == [], "an unpinned client must not be written back"


def test_metadata_may_be_absent_entirely():
    client = _client(metadata=None)
    db = _DB(client)

    result = _run(db, client)

    assert result.exit_code == 0
    assert db.updated == []


def test_an_unknown_node_id_is_reported():
    db = _DB(None)

    result = _run(db, None, node_id="99")

    assert "Invalid Node ID" in result.output
    assert db.updated == []


def test_the_command_accepts_the_access_key_the_logs_print():
    """The node's abort message names the client by ACCESS KEY.

    With click coercing the argument to int, following that message verbatim
    failed with "is not a valid integer" — the operator was left exactly as
    stuck as before the command existed.
    """
    client = _client(metadata={"noise_pubkey": "abc123"})
    db = _DB(client)

    with patch("hivemind_core.scripts.ClientDatabase", return_value=db), \
            patch("hivemind_core.scripts.resolve_client", return_value=client):
        result = CliRunner().invoke(reset_noise_pin, ["c0d14821bbece410349e2541"])

    assert result.exit_code == 0, result.output
    assert "not a valid integer" not in result.output
    assert db.updated == [client]
