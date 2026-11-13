"""T-0887: add-client --allow and multi-type allow-msg.

A new client, admin or not, still starts with an empty allowed_types
whitelist: the documented deny-by-default (HIVEMIND-POLICY-1 §4, README),
kept by Miro's ruling of 2026-09-13. What this adds is a way to grant types
while provisioning (add-client --allow) and several types in one allow-msg
call. The permission-writing commands fail closed: an empty type or a
target that does not resolve grants nothing.
"""
import os
import subprocess
import sys

import pytest
from click.testing import CliRunner

from hivemind_core.database import ClientDatabase
from hivemind_core import scripts as _scripts
from hivemind_core.scripts import add_client

ACCESS_KEY = "key-t0887"


@pytest.fixture(autouse=True)
def data_home(tmp_path, monkeypatch):
    """A fresh $XDG_DATA_HOME per test. The sqlite plugin resolves the client
    store at open time, and monkeypatch restores the environment afterwards."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return tmp_path


def _run_add_client(*extra, expect_ok=True):
    runner = CliRunner()
    result = runner.invoke(add_client, [
        "--access-key", ACCESS_KEY,
        "--password", "upright collar icefall sixpaned",
        "--allow-weak-password",
        *extra,
    ])
    if expect_ok:
        assert result.exit_code == 0, result.output
    return result


def _client():
    return ClientDatabase().get_client_by_api_key(ACCESS_KEY)


def test_a_new_client_without_allow_starts_with_an_empty_whitelist():
    result = _run_add_client()
    assert _client().allowed_types == []
    assert "will be DENIED on every message" in result.output


def test_a_new_admin_without_allow_starts_with_an_empty_whitelist():
    _run_add_client("--admin", "True")
    assert _client().is_admin is True
    assert _client().allowed_types == []


def test_allow_option_grants_exactly_what_was_passed():
    result = _run_add_client("--allow", "recognizer_loop:utterance",
                             "--allow", "mycroft.volume.get")
    assert _client().allowed_types == ["recognizer_loop:utterance", "mycroft.volume.get"]
    assert "Allowed Message Types: recognizer_loop:utterance, mycroft.volume.get" in result.output


def test_an_empty_allow_value_is_refused():
    result = _run_add_client("--allow", "", expect_ok=False)
    assert result.exit_code != 0
    assert "cannot be empty" in result.output
    assert _client() is None, "no client may be created with an empty message type"


def test_allow_msg_grants_several_types_in_one_call():
    _run_add_client("--allow", "recognizer_loop:utterance")
    result = CliRunner().invoke(_scripts.allow_msg,
                                ["ovos.utterance.handle", "mycroft.volume.set", ACCESS_KEY])
    assert result.exit_code == 0, result.output
    assert _client().allowed_types == ["recognizer_loop:utterance",
                                       "ovos.utterance.handle", "mycroft.volume.set"]


def test_allow_msg_single_type_with_a_target_grants_exactly_one():
    _run_add_client()
    result = CliRunner().invoke(_scripts.allow_msg, ["mycroft.volume.get", ACCESS_KEY])
    assert result.exit_code == 0, result.output
    assert _client().allowed_types == ["mycroft.volume.get"]


def test_allow_msg_with_an_unresolved_numeric_target_grants_nothing():
    """Review finding: on a one-client hub the prompt picks that client
    without asking, so a typo target must never fall back to it."""
    _run_add_client()
    result = CliRunner().invoke(_scripts.allow_msg, ["speak", "99"], input="")
    assert "Invalid Node ID!" in result.output
    assert _client().allowed_types == []


def test_allow_msg_with_a_mistyped_access_key_grants_nothing():
    _run_add_client()
    result = CliRunner().invoke(_scripts.allow_msg, ["speak", "key-t0888"], input="")
    assert "Invalid Node ID!" in result.output
    assert _client().allowed_types == []


def test_allow_msg_refuses_an_empty_type():
    _run_add_client()
    result = CliRunner().invoke(_scripts.allow_msg, ["", ACCESS_KEY])
    assert "cannot be empty" in result.output
    assert _client().allowed_types == []


def test_console_script_typo_target_on_a_one_client_hub_writes_nothing(data_home):
    """The review's exact repro through the installed console script:
    `hivemind-core allow-msg speak 99 </dev/null` on a one-client hub."""
    _run_add_client()
    env = dict(os.environ, XDG_DATA_HOME=str(data_home))
    script = os.path.join(os.path.dirname(sys.executable), "hivemind-core")
    proc = subprocess.run([script, "allow-msg", "speak", "99"], env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    assert "Invalid Node ID!" in proc.stdout, proc.stdout + proc.stderr
    assert _client().allowed_types == []
