from typing import List, Optional, Iterable

from ovos_utils.log import LOG

from hivemind_core.config import get_server_config
from hivemind_plugin_manager import DatabaseFactory
from hivemind_plugin_manager.database import Client


class ClientDatabase:

    def __init__(self, config=None):
        """
        Initialize the client database with the specified backend.
        """
        config = config or get_server_config()["database"]
        name = config["module"]
        db_class = DatabaseFactory.get_class(name)
        LOG.info(f"Database: {db_class.__name__}")
        self.db = db_class(**config.get(name, {}))

    def sync(self):
        """update db from disk if needed"""
        self.db.sync()

    def delete_client(self, key: str) -> bool:
        user = self.get_client_by_api_key(key)
        if user:
            return self.db.delete_item(user)
        return False

    def get_clients_by_name(self, name: str) -> List[Client]:
        return self.db.search_by_value("name", name)

    def get_client_by_api_key(self, api_key: str) -> Optional[Client]:
        search: List[Client] = self.db.search_by_value("api_key", api_key)
        if len(search):
            return search[0]
        return None

    def add_client(self,
                   name: str,
                   key: str = "",
                   admin: bool = False,
                   intent_blacklist: Optional[List[str]] = None,
                   skill_blacklist: Optional[List[str]] = None,
                   message_blacklist: Optional[List[str]] = None,
                   allowed_types: Optional[List[str]] = None,
                   crypto_key: Optional[str] = None,
                   password: Optional[str] = None) -> bool:
        if crypto_key is not None:
            crypto_key = crypto_key[:16]

        user = self.get_client_by_api_key(key)
        if user:
            # Update the existing client object directly
            if name:
                user.name = name
            if intent_blacklist:
                user.intent_blacklist = intent_blacklist
            if skill_blacklist:
                user.skill_blacklist = skill_blacklist
            if message_blacklist:
                user.message_blacklist = message_blacklist
            if allowed_types:
                user.allowed_types = allowed_types
            if admin is not None:
                user.is_admin = admin
            if crypto_key:
                user.crypto_key = crypto_key
            if password:
                user.password = password
            return self.db.update_item(user)

        user = Client(
            api_key=key,
            name=name,
            intent_blacklist=intent_blacklist,
            skill_blacklist=skill_blacklist,
            message_blacklist=message_blacklist,
            crypto_key=crypto_key,
            client_id=self.total_clients() + 1,
            is_admin=admin,
            password=password,
            allowed_types=allowed_types,
        )
        return self.db.add_item(user)

    def update_item(self, client: Client):
        self.db.update_item(client)

    def total_clients(self) -> int:
        return len(self.db)

    def __enter__(self):
        """Context handler"""
        return self

    def __iter__(self) -> Iterable[Client]:
        yield from self.db

    def __exit__(self, _type, value, traceback):
        """Commits changes and Closes the session"""
        try:
            self.db.commit()
        except Exception as e:
            LOG.error(e)
