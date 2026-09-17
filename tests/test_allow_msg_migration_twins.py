"""allow-msg and blacklist-msg treat a migration pair as one grant.

HIVEMIND-POLICY-1 §4: "A message whose `msg_type` is **not** in the
client's whitelist **MUST** be denied". The gate stays literal, so a
satellite that sends the spec spelling of a type the operator granted in
the legacy spelling is denied. The CLI writes both spellings of a pair on
a grant, and removes both on a revocation, so one command covers both.
"""
import pytest
from click.testing import CliRunner

from hivemind_core.database import ClientDatabase
from hivemind_core.scripts import add_client, allow_msg, blacklist_msg

ACCESS_KEY = "twins0access0key0for0tests"
PASSWORD = "correct-horse-battery-staple-twins-test"


@pytest.fixture(autouse=True)
def client_row(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    res = CliRunner().invoke(add_client, [
        "--access-key", ACCESS_KEY, "--password", PASSWORD, "--allow-weak-password"])
    assert res.exit_code == 0, res.output


def _types():
    return ClientDatabase().get_client_by_api_key(ACCESS_KEY).allowed_types


@pytest.mark.parametrize("granted,twin", [
    ("recognizer_loop:utterance", "ovos.utterance.handle"),
    ("ovos.utterance.handle", "recognizer_loop:utterance"),
    ("speak", "ovos.utterance.speak"),
    ("speak:b64_audio", "ovos.utterance.speak.b64"),
])
def test_allow_msg_writes_both_spellings(granted, twin):
    res = CliRunner().invoke(allow_msg, [granted, granted, ACCESS_KEY])
    assert res.exit_code == 0, res.output
    assert sorted(_types()) == sorted([granted, twin])
    assert _types().count(granted) == 1 and _types().count(twin) == 1


def test_allow_msg_type_without_twin_is_written_alone():
    CliRunner().invoke(allow_msg, ["my.skill.event", "my.skill.event", ACCESS_KEY])
    assert _types() == ["my.skill.event"]


def test_allow_msg_twin_already_granted_is_not_repeated():
    CliRunner().invoke(allow_msg, ["ovos.utterance.speak", "ovos.utterance.speak", ACCESS_KEY])
    CliRunner().invoke(allow_msg, ["speak", "speak", ACCESS_KEY])
    assert sorted(_types()) == ["ovos.utterance.speak", "speak"]


def test_blacklist_msg_removes_both_spellings():
    CliRunner().invoke(allow_msg, ["speak", "speak", ACCESS_KEY])
    res = CliRunner().invoke(blacklist_msg, ["ovos.utterance.speak", ACCESS_KEY])
    assert res.exit_code == 0, res.output
    assert _types() == []


def test_blacklist_msg_removes_a_twin_left_by_an_older_grant():
    # a row written before this change holds only the legacy spelling
    db = ClientDatabase()
    with db:
        c = db.get_client_by_api_key(ACCESS_KEY)
        c.allowed_types = ["recognizer_loop:utterance"]
        db.update_item(c)
    CliRunner().invoke(blacklist_msg, ["ovos.utterance.handle", ACCESS_KEY])
    assert _types() == []
