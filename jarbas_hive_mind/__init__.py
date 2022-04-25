from jarbas_hive_mind.nodes.master import HiveMind, HiveMindProtocol
from jarbas_hive_mind.configuration import CONFIGURATION
from jarbas_hive_mind.settings import DEFAULT_PORT
from jarbas_hive_mind.utils import create_self_signed_cert
from jarbas_hive_mind.exceptions import SecureConnectionFailed, ConnectionError
from jarbas_hive_mind.backends import HiveMindConnection, HiveMindListener


def get_listener(port=DEFAULT_PORT, max_connections=-1, bus=None):
    return HiveMindListener(port, max_connections, bus)


def get_connection(host="127.0.0.1", port=DEFAULT_PORT):
    return HiveMindConnection(host, port)
