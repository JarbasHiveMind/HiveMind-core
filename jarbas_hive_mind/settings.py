from os import makedirs
from os.path import isdir, join, expanduser

DATA_PATH = expanduser("~/jarbasHiveMind")

if not isdir(DATA_PATH):
    makedirs(DATA_PATH)

CERTS_PATH = join(DATA_PATH, "certs")
if not isdir(CERTS_PATH):
    makedirs(CERTS_PATH)


DB_PATH = join(DATA_PATH, "database")
if not isdir(DB_PATH):
    makedirs(DB_PATH)

CLIENTS_DB = "sqlite:///" + join(DB_PATH, "clients.db")

DEFAULT_PORT = 5678
USE_SSL = True

LOG_BLACKLIST = []

MYCROFT_WEBSOCKET_CONFIG = {
    "host": "0.0.0.0",
    "port": 8181,
    "route": "/core",
    "ssl": False
}
