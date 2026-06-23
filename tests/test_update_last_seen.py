"""Regression tests for issue #118 — update_last_seen None deref.

``update_last_seen`` looked up the client row by api-key and immediately
dereferenced it (``user.last_seen = ...``). When the key has been revoked
or never existed, ``get_client_by_api_key`` returns ``None`` and the
method crashes with ``AttributeError``. It must guard for ``None`` and
no-op instead.
"""
from unittest.mock import MagicMock

from hivemind_core.protocol import HiveMindListenerProtocol


def _make_protocol(db):
    proto = object.__new__(HiveMindListenerProtocol)
    proto.db = db
    return proto


def _mock_db(returned_user):
    db = MagicMock()
    # support the `with self.db:` context manager used by update_last_seen
    db.__enter__.return_value = db
    db.__exit__.return_value = False
    db.get_client_by_api_key.return_value = returned_user
    return db


def test_missing_key_does_not_crash():
    db = _mock_db(None)
    proto = _make_protocol(db)
    client = MagicMock(key="revoked-key")

    # must not raise AttributeError
    proto.update_last_seen(client)

    db.get_client_by_api_key.assert_called_once_with("revoked-key")
    db.update_item.assert_not_called()


def test_present_key_updates_last_seen():
    user = MagicMock(last_seen=-1)
    db = _mock_db(user)
    proto = _make_protocol(db)
    client = MagicMock(key="good-key")

    proto.update_last_seen(client)

    assert user.last_seen > 0
    db.update_item.assert_called_once_with(user)
