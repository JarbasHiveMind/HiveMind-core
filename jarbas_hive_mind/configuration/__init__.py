from json_database import JsonStorage
from os.path import join, exists, isdir
from os import makedirs
from jarbas_hive_mind.settings import DEFAULT_PORT, DATA_PATH, CERTS_PATH, DB_PATH


_DEFAULT_CONFIG = join(DATA_PATH, "HiveMind.conf")


def default_config():
    default = JsonStorage(_DEFAULT_CONFIG)
    default["max_connections"] = -1
    default["port"] = DEFAULT_PORT
    default["data_path"] = DATA_PATH
    default["ssl"] = {
        "certificates": CERTS_PATH,
        "ssl_certfile": "HiveMind.crt",
        "ssl_keyfile": "HiveMind.key"
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


if not exists(_DEFAULT_CONFIG):
    CONFIGURATION = default_config()
    CONFIGURATION.store()
else:
    CONFIGURATION = JsonStorage(_DEFAULT_CONFIG)

# ensure directories exist
if not isdir(CONFIGURATION["data_path"]):
    makedirs(CONFIGURATION["data_path"])

if not isdir(CONFIGURATION["ssl"]["certificates"]):
    makedirs(CONFIGURATION["ssl"]["certificates"])