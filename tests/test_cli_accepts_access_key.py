"""Most client-targeting commands declared ``node_id`` as ``type=int``, which
rejects the access key the tool itself tells operators to use (the node
names clients by access key in its logs — see ``rename-client``'s and
``reset-noise-pin``'s docstrings, and ``resolve_client``, which already
accepts either form). This covers every command that was still declaring
``type=int`` before this fix, plus ``allow-broadcast``/``blacklist-broadcast``
which hand-rolled their own ``int(node_id)`` lookup instead of going through
``resolve_client``.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from hivemind_core.scripts import (
    allow_broadcast,
    allow_escalate,
    allow_msg,
    allow_propagate,
    blacklist_broadcast,
    blacklist_escalate,
    blacklist_intent,
    blacklist_msg,
    blacklist_propagate,
    blacklist_skill,
    delete_client,
    make_admin,
    revoke_admin,
    set_metadata,
    unblacklist_intent as allow_intent,
    unblacklist_skill as allow_skill,
)

ACCESS_KEY = "c0d14821bbece410349e2541"


class _DB:
    def __init__(self, client):
        self.client = client
        self.updated = []
        self.deleted = []

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def __iter__(self):
        return iter([self.client] if self.client else [])

    def update_item(self, client):
        self.updated.append(client)

    def delete_client(self, api_key):
        self.deleted.append(api_key)


def _client(**kw):
    base = dict(
        name="kitchen",
        client_id=1,
        api_key=ACCESS_KEY,
        allowed_types=[],
        is_admin=False,
        can_escalate=False,
        can_propagate=False,
        can_broadcast=False,
        metadata={},
        password="pw",
    )
    base.update(kw)
    return SimpleNamespace(**base)


# Commands that take only a node_id argument (no other required args).
SIMPLE_COMMANDS = [
    make_admin,
    revoke_admin,
    allow_escalate,
    blacklist_escalate,
    allow_propagate,
    blacklist_propagate,
]


@pytest.mark.parametrize("cmd", SIMPLE_COMMANDS)
def test_access_key_is_accepted(cmd):
    client = _client()
    db = _DB(client)
    with patch("hivemind_core.scripts.ClientDatabase", return_value=db), \
            patch("hivemind_core.scripts.resolve_client", return_value=client) as resolve:
        result = CliRunner().invoke(cmd, [ACCESS_KEY])
    assert "not a valid integer" not in result.output
    assert result.exit_code == 0, result.output
    resolve.assert_called_once_with(db, ACCESS_KEY)


@pytest.mark.parametrize("cmd", SIMPLE_COMMANDS)
def test_numeric_id_still_works(cmd):
    client = _client()
    db = _DB(client)
    with patch("hivemind_core.scripts.ClientDatabase", return_value=db), \
            patch("hivemind_core.scripts.resolve_client", return_value=client) as resolve:
        result = CliRunner().invoke(cmd, ["1"])
    assert "not a valid integer" not in result.output
    assert result.exit_code == 0, result.output
    resolve.assert_called_once_with(db, "1")


@pytest.mark.parametrize("cmd,extra_arg", [
    (allow_msg, "recognizer_loop:utterance"),
    (blacklist_msg, "recognizer_loop:utterance"),
])
def test_msg_type_commands_accept_access_key(cmd, extra_arg):
    client = _client(allowed_types=[extra_arg] if cmd is blacklist_msg else [])
    db = _DB(client)
    with patch("hivemind_core.scripts.ClientDatabase", return_value=db), \
            patch("hivemind_core.scripts.resolve_client", return_value=client) as resolve:
        result = CliRunner().invoke(cmd, [extra_arg, ACCESS_KEY])
    assert "not a valid integer" not in result.output
    assert result.exit_code == 0, result.output
    resolve.assert_called_once_with(db, ACCESS_KEY)


@pytest.mark.parametrize("cmd,extra_arg", [
    (blacklist_skill, "skill.id"),
    (allow_skill, "skill.id"),
    (blacklist_intent, "intent.id"),
    (allow_intent, "intent.id"),
])
def test_skill_intent_commands_accept_access_key(cmd, extra_arg):
    client = _client(metadata={"skill_blacklist": ["skill.id"], "intent_blacklist": ["intent.id"]})
    db = _DB(client)
    with patch("hivemind_core.scripts.ClientDatabase", return_value=db), \
            patch("hivemind_core.scripts.resolve_client", return_value=client) as resolve:
        result = CliRunner().invoke(cmd, [extra_arg, ACCESS_KEY])
    assert "not a valid integer" not in result.output
    resolve.assert_called_once_with(db, ACCESS_KEY)


def test_set_metadata_accepts_access_key():
    client = _client(metadata={})
    db = _DB(client)
    with patch("hivemind_core.scripts.ClientDatabase", return_value=db), \
            patch("hivemind_core.scripts.resolve_client", return_value=client) as resolve:
        result = CliRunner().invoke(
            set_metadata, [ACCESS_KEY, "--key", "foo", "--value", "bar"])
    assert "not a valid integer" not in result.output
    assert result.exit_code == 0, result.output
    resolve.assert_called_once_with(db, ACCESS_KEY)


@pytest.mark.parametrize("cmd", [allow_broadcast, blacklist_broadcast])
def test_broadcast_commands_now_route_through_resolve_client(cmd):
    """These used to hand-roll ``int(node_id)`` lookups instead of using
    ``resolve_client``, so an access key could never work for them either."""
    client = _client(can_broadcast=(cmd is blacklist_broadcast), is_admin=True)
    db = _DB(client)
    with patch("hivemind_core.scripts.ClientDatabase", return_value=db), \
            patch("hivemind_core.scripts.resolve_client", return_value=client) as resolve:
        result = CliRunner().invoke(cmd, [ACCESS_KEY])
    assert "not a valid integer" not in result.output
    assert result.exit_code == 0, result.output
    resolve.assert_called_once_with(db, ACCESS_KEY)


def test_delete_client_accepts_access_key_with_yes():
    client = _client()
    db = _DB(client)
    with patch("hivemind_core.scripts.ClientDatabase", return_value=db), \
            patch("hivemind_core.scripts.resolve_client", return_value=client) as resolve:
        result = CliRunner().invoke(delete_client, [ACCESS_KEY, "--yes"])
    assert "not a valid integer" not in result.output
    assert result.exit_code == 0, result.output
    resolve.assert_called_once_with(db, ACCESS_KEY)
    assert db.deleted == [ACCESS_KEY]


def test_delete_client_bare_with_one_client_does_not_delete_without_confirmation():
    client = _client()
    db = _DB(client)
    with patch("hivemind_core.scripts.ClientDatabase", return_value=db), \
            patch("hivemind_core.scripts.resolve_client", return_value=client):
        # No --yes, and stdin gives no input -> click.confirm reads EOF, which
        # click treats as "no" (abort), never as an implicit "yes".
        result = CliRunner().invoke(delete_client, [ACCESS_KEY], input="n\n")
    assert db.deleted == [], "must not delete without an explicit confirmation"


def test_delete_client_yes_flag_bypasses_confirmation():
    client = _client()
    db = _DB(client)
    with patch("hivemind_core.scripts.ClientDatabase", return_value=db), \
            patch("hivemind_core.scripts.resolve_client", return_value=client):
        result = CliRunner().invoke(delete_client, [ACCESS_KEY, "--yes"])
    assert result.exit_code == 0, result.output
    assert db.deleted == [ACCESS_KEY]
