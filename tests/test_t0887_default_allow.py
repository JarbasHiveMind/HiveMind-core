"""T-0887: add-client provisioning defaults and multi-type allow-msg.

A new satellite created without an explicit grant used to land with an
empty allowed_types whitelist and every message denied with
hive.policy.denied until allow-msg ran twice (joergz's report, HiveMind
Support room 2026-09-11/12). These tests pin the provisioning-layer
behaviour on top of the deny-by-default gate: the gate itself is
unchanged (HIVEMIND-POLICY-1 §3).
"""
import os
import tempfile

from click.testing import CliRunner

from hivemind_core.database import ClientDatabase
from hivemind_core import scripts as _scripts
from hivemind_core.scripts import add_client


data_homes = []


def _isolate_data_home():
    """A fresh $XDG_DATA_HOME per call — the sqlite plugin resolves the
    client store at open time, so an env var set after import is still
    honoured (xdg_utils reads the environment on every call)."""
    home = tempfile.mkdtemp(prefix="hm0887-")
    data_homes.append(home)
    os.environ["XDG_DATA_HOME"] = home
    return home


def _run_add_client(*extra):
    _isolate_data_home()
    runner = CliRunner()
    result = runner.invoke(add_client, [
        "--access-key", "key-t0887",
        "--password", "upright collar icefall sixpaned",
        "--allow-weak-password",
        *extra,
    ])
    assert result.exit_code == 0, result.output
    return result




def test_new_client_without_allow_gets_the_measured_defaults():
    _run_add_client()
    db = ClientDatabase()
    user = db.get_client_by_api_key("key-t0887")
    assert user.allowed_types == _scripts.VOICE_SATELLITE_DEFAULT_ALLOW, \
        "a voice satellite without --allow must get the measured whitelist"

    # the measured pair: the gate is not twin-aware yet, both spellings
    # must be present so either satellite stack can speak
    assert "recognizer_loop:utterance" in user.allowed_types
    assert "ovos.utterance.handle" in user.allowed_types


def test_allow_option_grants_exactly_what_was_passed():
    _run_add_client("--allow", "recognizer_loop:utterance",
                    "--allow", "mycroft.volume.get")
    db = ClientDatabase()
    user = db.get_client_by_api_key("key-t0887")
    assert user.allowed_types == ["recognizer_loop:utterance", "mycroft.volume.get"], \
        "--allow replaces the defaults entirely, it does not append to them"


def test_add_client_prints_the_granted_types():
    result = _run_add_client("--allow", "recognizer_loop:utterance")
    assert "Allowed Message Types:" in result.output
    assert "recognizer_loop:utterance" in result.output

    result = _run_add_client()
    assert "Allowed Message Types:" in result.output
    assert "ovos.utterance.handle" in result.output


def test_repeated_allow_msg_grants_several_types_in_one_call():
    _run_add_client("--allow", "recognizer_loop:utterance")
    allow_msg = _scripts.allow_msg
    runner = CliRunner()
    result = runner.invoke(allow_msg, [
        "ovos.utterance.handle", "mycroft.volume.set", "key-t0887",
    ])
    assert result.exit_code == 0, result.output
    db = ClientDatabase()
    user = db.get_client_by_api_key("key-t0887")
    assert "ovos.utterance.handle" in user.allowed_types
    assert "mycroft.volume.set" in user.allowed_types
    assert "recognizer_loop:utterance" in user.allowed_types


def test_allow_msg_dot_notation_backward_compatible_single_type():
    # old form: allow-msg <type> <node_id> — still exactly one grant
    _run_add_client()
    allow_msg = _scripts.allow_msg
    runner = CliRunner()
    result = runner.invoke(allow_msg, ["mycroft.volume.get", "key-t0887"])
    assert result.exit_code == 0, result.output
    db = ClientDatabase()
    user = db.get_client_by_api_key("key-t0887")
    assert user.allowed_types.count("mycroft.volume.get") == 1
