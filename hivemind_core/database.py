# hivemind-core
# Copyright (C) 2026 Casimiro Ferreira
# SPDX-License-Identifier: Apache-2.0
import threading
from typing import Any, Dict, List, Optional, Iterable

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
        self._last_seen_lock = threading.Lock()

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
        direct_lookup = getattr(self.db, "get_client_by_api_key", None)
        if callable(direct_lookup):
            return direct_lookup(api_key)
        search: List[Client] = self.db.search_by_value("api_key", api_key)
        if len(search):
            return search[0]
        return None

    def get_client_by_id(self, client_id: int) -> Optional[Client]:
        return self.db.get_client_by_id(client_id)

    def refresh(self, client_id: int) -> Optional[Client]:
        return self.db.refresh(client_id)

    def add_client(self,
                   name: str,
                   key: str = "",
                   admin: bool = False,
                   allowed_types: Optional[List[str]] = None,
                   crypto_key: Optional[str] = None,
                   password: Optional[str] = None,
                   metadata: Optional[Dict[str, Any]] = None,
                   # Deprecated kwargs — folded into metadata. Kept so the
                   # CLI and external callers using the old signature keep
                   # working. Client.deserialize handles the same migration
                   # on the read side. See HiveMind-core#85.
                   intent_blacklist: Optional[List[str]] = None,
                   skill_blacklist: Optional[List[str]] = None,
                   message_blacklist: Optional[List[str]] = None) -> bool:
        if crypto_key is not None:
            crypto_key = crypto_key[:16]

        # Migrate any legacy blacklist kwargs into metadata.
        meta = dict(metadata) if metadata else {}
        for k, v in (("skill_blacklist", skill_blacklist),
                     ("intent_blacklist", intent_blacklist),
                     ("message_blacklist", message_blacklist)):
            if v:
                meta.setdefault(k, list(v))

        user = self.get_client_by_api_key(key)
        if user:
            if name:
                user.name = name
            if allowed_types:
                user.allowed_types = allowed_types
            if admin is not None:
                user.is_admin = admin
            if crypto_key:
                user.crypto_key = crypto_key
            if password:
                user.password = password
            if meta:
                # merge — don't blow away existing metadata
                merged = dict(user.metadata)
                merged.update(meta)
                user.metadata = merged
            return self.db.update_item(user)

        user = Client(
            api_key=key,
            name=name,
            crypto_key=crypto_key,
            client_id=self.total_clients() + 1,
            is_admin=admin,
            password=password,
            allowed_types=allowed_types or [],
            metadata=meta,
        )
        return self.db.add_item(user)

    def update_item(self, client: Client):
        self.db.update_item(client)

    def update_last_seen(self, api_key: str, seen_at: float) -> bool:
        """Advance a client's activity timestamp without moving it backward.

        Current bundled backends expose an atomic implementation. The locked
        fallback preserves compatibility with third-party database plugins and
        older bundled releases used during rolling upgrades.
        """
        backend_update = getattr(self.db, "update_last_seen", None)
        if callable(backend_update):
            return bool(backend_update(api_key, seen_at))

        with self._last_seen_lock:
            user = self.get_client_by_api_key(api_key)
            if user is None:
                return False
            current = getattr(user, "last_seen", -1)
            if current is None or seen_at > current:
                user.last_seen = seen_at
                return bool(self.db.update_item(user))
            return True

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
