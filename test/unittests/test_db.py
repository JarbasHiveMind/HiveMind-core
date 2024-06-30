import os
import unittest
from hivemind_core.database import ClientDatabase, Client


class TestDB(unittest.TestCase):

    def setUp(self):
        self.key = os.urandom(8).hex()
        self.access_key = os.urandom(16).hex()
        self.password = None

    def test_add_entry(self):
        with ClientDatabase() as db:
            n = db.total_clients()
            name = f"HiveMind-Node-{n}"
            user = db.add_client(name, self.access_key, crypto_key=self.key, password=self.password)

            # verify data
            self.assertTrue(isinstance(user, Client))
            self.assertEqual(user.name, name)
            self.assertEqual(user.api_key, self.access_key)

            # test search entry in db
            node_id = db.get_item_id(user)
            self.assertEqual(node_id, n)

            user2 = db.get_client_by_api_key(self.access_key)
            self.assertEqual(user, user2)

            for u in db.get_clients_by_name(name):
                self.assertEqual(user.name, u.name)

            # test delete entry
            db.delete_client(self.access_key)
            user = db.get_client_by_api_key(self.access_key)
            self.assertIsNone(user)

    def test_update_entry(self):
        with ClientDatabase() as db:
            name = "TestNode"
            user = db.add_client(name, self.access_key, crypto_key=self.key, password=self.password)
            self.assertEqual(user.name, name)

            # Update client name
            new_name = "UpdatedNode"
            updated_user = db.add_client(new_name, self.access_key, crypto_key=self.key, password=self.password)
            self.assertEqual(updated_user.name, new_name)

            # Verify updated entry
            user2 = db.get_client_by_api_key(self.access_key)
            self.assertEqual(user2.name, new_name)

    def test_search_nonexistent_entry(self):
        with ClientDatabase() as db:
            user = db.get_client_by_api_key("nonexistent_key")
            self.assertIsNone(user)

    def test_json_db_implementation(self):
        with ClientDatabase(backend="json") as db:
            name = f"HiveMind-Node-TestJson"
            user = db.add_client(name, self.access_key, crypto_key=self.key, password=self.password)
            self.assertTrue(isinstance(user, Client))
            self.assertEqual(user.name, name)
            self.assertEqual(user.api_key, self.access_key)

    def test_delete_and_reuse_client_id(self):
        with ClientDatabase() as db:
            name = "TestNodeForDelete"
            user = db.add_client(name, self.access_key, crypto_key=self.key, password=self.password)
            client_id = db.get_item_id(user)

            db.delete_client(self.access_key)
            deleted_user = db.get_client_by_api_key(self.access_key)
            self.assertIsNone(deleted_user)

            new_access_key = os.urandom(16).hex()
            new_user = db.add_client("NewNode", new_access_key, crypto_key=self.key, password=self.password)
            new_client_id = db.get_item_id(new_user)
            self.assertNotEqual(client_id, new_client_id)


if __name__ == '__main__':
    unittest.main()
