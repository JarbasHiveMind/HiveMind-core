"""A type granted twice must still be revoked by one blacklist-msg.

HIVEMIND-POLICY-1 §4: a revocation takes effect. add-client and allow-msg
stored a repeated type twice, and blacklist-msg removed one copy. The CLI
printed "Blacklisted" while the row still granted the type. A type name with
white space in it never matches a message type, so it is refused.
"""
import pytest
from click.testing import CliRunner

from hivemind_core.database import ClientDatabase
from hivemind_core.scripts import add_client, allow_msg, blacklist_msg

ACCESS_KEY = "dedupe0access0key0for0tests"
PASSWORD = "correct-horse-battery-staple-dedupe-test"


@pytest.fixture(autouse=True)
def data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return tmp_path


def _add(*extra):
    return CliRunner().invoke(add_client, [
        "--access-key", ACCESS_KEY, "--password", PASSWORD, "--allow-weak-password", *extra])


def _row():
    return ClientDatabase().get_client_by_api_key(ACCESS_KEY)


def test_add_client_twice_granted_type_is_revoked_once():
    assert _add("--allow", "speak", "--allow", "speak").exit_code == 0
    assert _row().allowed_types == ["speak"]
    res = CliRunner().invoke(blacklist_msg, ["speak", ACCESS_KEY])
    assert "Blacklisted 'speak'" in res.output
    assert "speak" not in _row().allowed_types


def test_allow_msg_twice_in_one_call_is_revoked_once():
    assert _add().exit_code == 0
    res = CliRunner().invoke(allow_msg, ["ping", "ping", ACCESS_KEY])
    assert res.exit_code == 0, res.output
    assert _row().allowed_types == ["ping"]
    CliRunner().invoke(blacklist_msg, ["ping", ACCESS_KEY])
    assert "ping" not in _row().allowed_types


def test_blacklist_msg_removes_every_stored_copy():
    """A row written before this fix can already hold a repeat."""
    assert _add("--allow", "speak").exit_code == 0
    with ClientDatabase() as db:
        user = db.get_client_by_api_key(ACCESS_KEY)
        user.allowed_types = ["speak", "speak", "ping"]
        db.update_item(user)
    CliRunner().invoke(blacklist_msg, ["speak", ACCESS_KEY])
    assert _row().allowed_types == ["ping"]


def test_add_client_refuses_whitespace_in_a_type():
    res = _add("--allow", " speak")
    assert res.exit_code != 0
    assert _row() is None


def test_allow_msg_refuses_whitespace_in_a_type():
    assert _add().exit_code == 0
    res = CliRunner().invoke(allow_msg, ["speak ", ACCESS_KEY])
    assert "nothing was granted" in res.output
    assert _row().allowed_types == []
