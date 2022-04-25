from os import makedirs
from os.path import isdir, join
from ovos_utils.xdg_utils import xdg_data_home

DATA_PATH = join(xdg_data_home(), "jarbasHiveMind")
if not isdir(DATA_PATH):
    makedirs(DATA_PATH)

DEFAULT_PORT = 5678
USE_SSL = True

LOG_BLACKLIST = []

MYCROFT_WEBSOCKET_CONFIG = {
    "host": "0.0.0.0",
    "port": 8181,
    "route": "/core",
    "ssl": False
}
