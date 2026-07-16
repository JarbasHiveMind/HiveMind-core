"""Regression tests for missing clients and queued last_seen timestamps."""
import queue
import threading
from unittest.mock import MagicMock

from hivemind_core.protocol import HiveMindListenerProtocol


def _make_protocol(db):
    proto = object.__new__(HiveMindListenerProtocol)
    proto.db = db
    return proto


def _mock_db(update_result):
    db = MagicMock()
    db.__enter__.return_value = db
    db.__exit__.return_value = False
    db.update_last_seen.return_value = update_result
    return db


def test_missing_key_does_not_crash():
    db = _mock_db(False)
    proto = _make_protocol(db)
    client = MagicMock(key="revoked-key")

    # must not raise AttributeError
    proto.update_last_seen(client)

    db.update_last_seen.assert_called_once()


def test_present_key_updates_last_seen():
    db = _mock_db(True)
    proto = _make_protocol(db)
    client = MagicMock(key="good-key")

    proto.update_last_seen(client)

    db.update_last_seen.assert_called_once()


def test_worker_preserves_queued_seen_at_timestamp():
    db = _mock_db(True)
    proto = _make_protocol(db)
    proto._last_seen_queue = queue.Queue()
    proto._last_seen_stop = threading.Event()
    client = MagicMock(key="good-key")
    proto._last_seen_queue.put((client, 123.5))
    proto._last_seen_stop.set()

    proto._last_seen_worker(proto._last_seen_queue)

    db.update_last_seen.assert_called_once_with("good-key", 123.5)
