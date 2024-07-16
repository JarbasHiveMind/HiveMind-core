import abc
import json
from functools import wraps
from typing import List, Dict, Union, Any, Optional, Iterable

from json_database import JsonDatabaseXDG
from ovos_utils.log import LOG


def cast_to_client_obj():
    """
    Decorator to cast the return value of a function to a Client object or a list of Client objects.
    """
    valid_kwargs = (
        "client_id", "api_key", "name", "description", "is_admin", "last_seen",
        "blacklist", "allowed_types", "crypto_key", "password", "can_broadcast",
        "can_escalate", "can_propagate"
    )

    def _handler(func):
        def _cast(ret):
            if ret is None or isinstance(ret, Client):
                return ret
            if isinstance(ret, list):
                return [_cast(r) for r in ret]
            if isinstance(ret, dict):
                if not all((k in valid_kwargs for k in ret.keys())):
                    raise RuntimeError(f"{func.__name__} returned a dict with unknown keys: {ret.keys()}")
                return Client(**ret)

            raise TypeError(
                "cast_to_client_obj decorator can only be used in functions that return None, dict, Client or a list of those types"
            )

        @wraps(func)
        def call_function(*args, **kwargs):
            ret = func(*args, **kwargs)
            return _cast(ret)

        return call_function

    return _handler


class Client:
    def __init__(
            self,
            client_id: int,
            api_key: str,
            name: str = "",
            description: str = "",
            is_admin: bool = False,
            last_seen: float = -1,
            blacklist: Optional[Dict[str, List[str]]] = None,
            allowed_types: Optional[List[str]] = None,
            crypto_key: Optional[str] = None,
            password: Optional[str] = None,
            can_broadcast: bool = True,
            can_escalate: bool = True,
            can_propagate: bool = True,
    ):
        self.client_id = client_id
        self.description = description
        self.api_key = api_key
        self.name = name
        self.last_seen = last_seen
        self.is_admin = is_admin
        self.crypto_key = crypto_key
        self.password = password
        self.blacklist = blacklist or {"messages": [], "skills": [], "intents": []}
        self.allowed_types = allowed_types or ["recognizer_loop:utterance",
                                               "recognizer_loop:record_begin",
                                               "recognizer_loop:record_end",
                                               "recognizer_loop:audio_output_start",
                                               "recognizer_loop:audio_output_end",
                                               "ovos.common_play.SEI.get.response"]
        if "recognizer_loop:utterance" not in self.allowed_types:
            self.allowed_types.append("recognizer_loop:utterance")
        self.can_broadcast = can_broadcast
        self.can_escalate = can_escalate
        self.can_propagate = can_propagate

    def __getitem__(self, item: str) -> Any:
        if item in self.__dict__:
            return self.__dict__[item]
        raise KeyError(f"Unknown key: {item}")

    def __setitem__(self, key: str, value: Any):
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            raise ValueError(f"Unknown property: {key}")

    def __eq__(self, other: Union[object, dict]) -> bool:
        if isinstance(other, dict):
            return self.__dict__ == other
        if isinstance(other, Client):
            return self.__dict__ == other.__dict__
        return False

    def __repr__(self) -> str:
        return str(self.__dict__)


class AbstractDB:
    @abc.abstractmethod
    def get_item_id(self, client: Client) -> str:
        pass

    @abc.abstractmethod
    def add_item(self, client: Client):
        pass

    @abc.abstractmethod
    def update_item(self, item_id: str, client: Client):
        pass

    def delete_item(self, client: Client):
        item_id = self.get_item_id(client)
        self.update_item(item_id, Client(-1, api_key="revoked"))

    @abc.abstractmethod
    def search_by_value(self, key: str, val: str):
        pass

    @abc.abstractmethod
    def __len__(self):
        return 0

    @abc.abstractmethod
    def commit(self):
        pass


class JsonDB(AbstractDB):
    def __init__(self):
        self._db = JsonDatabaseXDG(name="clients", subfolder="hivemind")

    def get_item_id(self, client: Client) -> str:
        return self._db.get_item_id(client.__dict__)

    def add_item(self, client: Client):
        self._db.add_item(client.__dict__)

    def update_item(self, item_id: str, client: Client):
        self._db.update_item(item_id, client.__dict__)

    @cast_to_client_obj()
    def search_by_value(self, key: str, val: str) -> List[Client]:
        return self._db.search_by_value(key, val)

    def __len__(self):
        return len(self._db)

    def commit(self):
        self._db.commit()


class RedisDB(AbstractDB):
    def __init__(self):
        try:
            import redis
            from redis.commands.json.path import Path
            from redis.commands.search.query import Query
            from redis.commands.search.field import TextField, NumericField
            from redis.commands.search.indexDefinition import IndexDefinition, IndexType
        except ImportError:
            LOG.error("'pip install redis[hiredis]'")
            raise

        self._Path = Path
        self._Query = Query
        # TODO - host/port from config
        self.r = redis.Redis(host="localhost", port=6379)
        self.rs = self.r.ft("idx:clients")

        # Create the search index if it doesn't exist
        try:
            self.rs.info()
        except:
            schema = (
                TextField("api_key"),
                NumericField("client_id")
            )
            index_def = IndexDefinition(prefix=["client:"])
            self.rs.create_index(schema, definition=index_def)

    def get_item_id(self, client: Client) -> str:
        try:
            search = self.rs.search(self._Query(f"@api_key:{client.api_key}"))
            if search.total == 0:
                raise ValueError("Client not found")
            return search.docs[0].id
        except Exception as e:
            LOG.error(f"Failed to get item ID: {e}")
            raise

    def add_item(self, client: Client):
        try:
            client_id = len(self) + 1
            client_key = f"client:{client_id}"
            client_data = client.__dict__
            self.r.json().set(client_key, self._Path.root_path(), client_data)
            self.rs.add_document(
                client_key,
                api_key=client.api_key,
                client_id=client.client_id
            )
        except Exception as e:
            LOG.error(f"Failed to add item: {e}")
            raise

    def update_item(self, item_id: str, client: Client):
        try:
            client_key = f"client:{item_id}"
            client_data = client.__dict__
            self.r.json().set(client_key, self._Path.root_path(), client_data)
            self.rs.update_document(
                client_key,
                api_key=client.api_key,
                client_id=client.client_id
            )
        except Exception as e:
            LOG.error(f"Failed to update item: {e}")
            raise

    @cast_to_client_obj()
    def search_by_value(self, key: str, val: str) -> List[Client]:
        try:
            search = self.rs.search(self._Query(f"@{key}:{val}"))
            return [json.loads(doc.json) for doc in search.docs]
        except Exception as e:
            LOG.error(f"Search by value failed: {e}")
            raise

    @cast_to_client_obj()
    def get_all_clients(self, sort_by: str = "client_id", asc: bool = True) -> Optional[List[Client]]:
        try:
            search = self.rs.search(self._Query("@client_id:[0 +inf]").sort_by(sort_by, asc))
            return [json.loads(client.json) for client in search.docs]
        except Exception as e:
            LOG.error(f"Failed to get all clients: {e}")
            raise

    def __len__(self):
        try:
            return len(self.get_all_clients())
        except Exception as e:
            LOG.error(f"Failed to get database length: {e}")
            return 0

    def commit(self):
        # Redis operations are usually atomic, no explicit commit needed
        pass


class ClientDatabase:
    valid_backends = ["json", "redis"]

    def __init__(self, backend="json"):
        """
        Initialize the client database with the specified backend.
        """
        if backend not in self.valid_backends:
            raise NotImplementedError(f"{backend} not supported, choose one of {self.valid_backends}")

        if backend == "json":
            self.db = JsonDB()
        else:
            self.db = RedisDB()

    def get_item_id(self, client: Client):
        return self.db.get_item_id(client)

    def delete_client(self, key: str) -> bool:
        user = self.get_client_by_api_key(key)
        if user:
            self.db.delete_item(user)
            return True
        return False

    @cast_to_client_obj()
    def get_client_by_api_key(self, api_key: str) -> Optional[Client]:
        search = self.db.search_by_value("api_key", api_key)
        if len(search):
            return search[0]
        return None

    @cast_to_client_obj()
    def get_clients_by_name(self, name: str) -> List[Client]:
        return self.db.search_by_value("name", name)

    @cast_to_client_obj()
    def add_client(
            self,
            name: str,
            key: str = "",
            admin: bool = False,
            blacklist: Optional[Dict[str, Any]] = None,
            allowed_types: Optional[List[str]] = None,
            crypto_key: Optional[str] = None,
            password: Optional[str] = None,
    ) -> Client:
        if crypto_key is not None:
            crypto_key = crypto_key[:16]
        user = self.get_client_by_api_key(key)
        if user:
            item_id = self.db.get_item_id(user)
            if name:
                user["name"] = name
            if blacklist:
                user["blacklist"] = blacklist
            if allowed_types:
                user["allowed_types"] = allowed_types
            if admin is not None:
                user["is_admin"] = admin
            if crypto_key:
                user["crypto_key"] = crypto_key
            if password:
                user["password"] = password
            self.db.update_item(item_id, user)
        else:
            user = Client(
                api_key=key,
                name=name,
                blacklist=blacklist,
                crypto_key=crypto_key,
                client_id=self.total_clients() + 1,
                is_admin=admin,
                password=password,
                allowed_types=allowed_types,
            )
            self.db.add_item(user)
        return user

    def total_clients(self) -> int:
        return len(self.db)

    def __enter__(self):
        """Context handler"""
        return self

    def __exit__(self, _type, value, traceback):
        """Commits changes and Closes the session"""
        try:
            self.db.commit()
        except Exception as e:
            LOG.error(e)
