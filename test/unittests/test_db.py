"""Unit tests for hivemind_core.database ClientDatabase."""
import unittest
from unittest.mock import MagicMock

from hivemind_core.database import ClientDatabase
from hivemind_plugin_manager.database import Client


class TestClientDatabase(unittest.TestCase):

    def _make_db(self):
        db = MagicMock()
        db.__enter__ = lambda s: s
        db.__exit__ = MagicMock(return_value=False)
        client_db = ClientDatabase.__new__(ClientDatabase)
        client_db.db = db
        return client_db, db

    def test_delete_client(self):
        client_db, db = self._make_db()
        db.delete_item.return_value = True
        client_db.get_client_by_api_key = MagicMock(
            return_value=Client(client_id=1, api_key="k")
        )
        result = client_db.delete_client("k")
        self.assertTrue(result)
        db.delete_item.assert_called_once()

    def test_delete_client_not_found(self):
        client_db, db = self._make_db()
        client_db.get_client_by_api_key = MagicMock(return_value=None)
        result = client_db.delete_client("missing-key")
        self.assertFalse(result)

    def test_get_clients_by_name(self):
        client_db, db = self._make_db()
        client = Client(client_id=1, api_key="k", name="TestNode")
        db.search_by_value.return_value = [client]
        clients = client_db.get_clients_by_name("TestNode")
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0].name, "TestNode")
        db.search_by_value.assert_called_once_with("name", "TestNode")


if __name__ == "__main__":
    unittest.main()
