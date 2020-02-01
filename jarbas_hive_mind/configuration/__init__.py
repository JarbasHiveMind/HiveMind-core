from json_database import JsonStorage
from os.path import expanduser, join, exists

DATA_PATH = expanduser("~/.jarbasHiveMind/hive.conf")


def default_config():
    default = JsonStorage(DATA_PATH)

    DB_PATH = join(DATA_PATH, "database")

    default["port"] = 5678
    default["data_path"] = DATA_PATH
    default["ssl"] = {
        "enable": False,
        "ssl_certfile": join(DATA_PATH, "certs", "hivemind.crt"),
        "ssl_keyfile": join(DATA_PATH, "certs", "hivekey.crt")
    }
    default["database"] = {
        "clients": "sqlite:///" + join(DB_PATH, "clients.db")
    }
    default["log_blacklist"] = []
    default["mycroft_bus"] = {
        "host": "0.0.0.0",
        "port": 8181,
        "route": "/core",
        "ssl": False
    }

    return default


if not exists(DATA_PATH):
    CONFIGURATION = default_config()
    CONFIGURATION.store()
else:
    CONFIGURATION = JsonStorage(DATA_PATH)
