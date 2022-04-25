import base64

from jarbas_hive_mind.nodes.master import HiveMind, HiveMindProtocol
from jarbas_hive_mind.configuration import CONFIGURATION
from jarbas_hive_mind.settings import DEFAULT_PORT
from jarbas_hive_mind.utils import create_self_signed_cert
from jarbas_hive_mind.exceptions import SecureConnectionFailed, ConnectionError
from ovos_utils.messagebus import get_mycroft_bus
from ovos_utils.log import LOG
from os.path import join, exists, isfile


class HiveMindAbstractConnection:
    _autorun = True

    def __init__(self, host="0.0.0.0", port=DEFAULT_PORT,
                 accept_self_signed=True):
        host = host.replace("https://", "wss://").replace("http://", "ws://")
        if "wss://" in host:
            self._secure = True
        else:
            self._secure = False

        host = host.replace("wss://", "").replace("ws://", "")
        self.host = host
        self.port = port
        self.loop = None
        self.ws = None

        self.accept_self_signed = accept_self_signed

    @property
    def is_secure(self):
        return self._secure

    @property
    def address(self):
        if self.is_secure:
            if "wss://" in self.host:
                return self.host + u":" + str(self.port)
            return "wss://" + self.host + u":" + str(self.port)
        else:
            if "ws://" in self.host:
                return self.host + u":" + str(self.port)
            return "ws://" + self.host + u":" + str(self.port)

    @property
    def peer(self):
        return "tcp4:" + self.host + ":" + str(self.port)

    @staticmethod
    def get_headers(name, key):
        # Note that keys can be shared across users
        # name is not used for auth
        name = name.replace(":", "__")
        authorization = bytes(name + ":" + key, encoding="utf-8")
        key = base64.b64encode(authorization)
        headers = {'authorization': key}
        return headers

    def secure_connect(self, component):
        self._secure = True
        self.ws = component
        self.ws.bind(self)
        LOG.info("Connecting securely to " + self.address)
        self.run()

    def unsafe_connect(self, component):
        self._secure = False
        self.ws = component
        self.ws.bind(self)
        LOG.info("Connecting to " + self.address)
        LOG.warning("This listener is unsecured")
        self.run()

    def run(self):
        raise NotImplementedError

    def connect(self, component):
        try:
            if self.is_secure:
                try:
                    return self.secure_connect(component)
                except ConnectionError:
                    raise SecureConnectionFailed
            else:
                return self.unsafe_connect(component)
        except Exception as e:
            LOG.exception(e)
            raise e

    def close(self):
        raise NotImplementedError


class HiveMindAbstractListener:
    _autorun = True
    default_factory = HiveMind
    default_protocol = HiveMindProtocol

    def __init__(self, port=DEFAULT_PORT, max_cons=-1, bus=None,
                 host="0.0.0.0", accept_self_signed=True):
        self.host = host
        self.port = port
        self.max_cons = max_cons
        self._use_ssl = CONFIGURATION["ssl"].get("use_ssl", False)
        self.certificate_path = CONFIGURATION["ssl"]["certificates"]
        self._key_file = CONFIGURATION["ssl"].get("ssl_keyfile",
                                                  "HiveMind.key")
        self._cert_file = CONFIGURATION["ssl"].get("ssl_certfile",
                                                   "HiveMind.crt")
        self.bus = bus
        self.accept_self_signed = accept_self_signed

    def bind(self, bus=None):
        # TODO read config for bus options
        self.bus = bus or get_mycroft_bus()

    @property
    def ssl_key(self):
        if isfile(self._key_file):
            return self._key_file
        return join(self.certificate_path, self._key_file)

    @property
    def ssl_cert(self):
        if isfile(self._cert_file):
            return self._cert_file
        return join(self.certificate_path, self._cert_file)

    def load_config(self, config=CONFIGURATION):
        # read configuration
        self.port = config["port"]
        self.max_cons = config.get("max_connections", -1)

        ssl_config = config.get("ssl", {})
        self.certificate_path = ssl_config.get("certificates",
                                               self.certificate_path)
        self._key_file = ssl_config.get("ssl_keyfile", self._key_file)
        self._cert_file = ssl_config.get("ssl_certfile", self._cert_file)
        self._use_ssl = ssl_config.get("use_ssl", True)

        # generate self signed keys
        if not exists(self.ssl_key) and self.accept_self_signed and \
                self.is_secure:
            LOG.warning("ssl keys dont exist, creating self signed certificates")
            self.generate_keys(self.certificate_path)

    @property
    def is_secure(self):
        return self._use_ssl

    @property
    def address(self):
        if self.is_secure:
            return "wss://" + self.host + ":" + str(self.port)
        return "ws://" + self.host + ":" + str(self.port)

    @property
    def peer(self):
        return "tcp4:" + self.host + ":" + str(self.port)

    @staticmethod
    def generate_keys(path=CONFIGURATION["ssl"]["certificates"],
                      key_name="HiveMind"):
        LOG.info("creating self signed SSL keys")
        name = key_name.split("/")[-1].replace(".key", "")
        create_self_signed_cert(path, name)
        cert = path + "/" + name + ".crt"
        key = path + "/" + name + ".key"
        LOG.info("key created at: " + key)
        LOG.info("crt created at: " + cert)

    def secure_listen(self, key=None, cert=None, factory=None, protocol=None):
        self._use_ssl = True
        self._ssl_key = key or self.ssl_key
        self._ssl_cert = cert or self.ssl_cert

        self.factory = factory or self.default_factory(bus=self.bus)
        self.factory.protocol = protocol or self.default_protocol
        if self.max_cons >= 0:
            self.factory.setProtocolOptions(maxConnections=self.max_cons)
        self.factory.bind(self)

        if self._autorun:
            self.run()
        return factory

    def unsafe_listen(self, factory=None, protocol=None):
        self._use_ssl = False
        self.factory = factory or self.default_factory(bus=self.bus)
        self.factory.protocol = protocol or self.default_protocol
        if self.max_cons >= 0:
            self.factory.setProtocolOptions(maxConnections=self.max_cons)
        self.factory.bind(self)

        if self._autorun:
            self.run()
        return factory

    def run(self):
        raise NotImplementedError

    def listen(self, factory=None, protocol=None):
        if self.is_secure:
            return self.secure_listen(factory=factory, protocol=protocol)
        else:
            return self.unsafe_listen(factory=factory, protocol=protocol)

    def stop(self):
        raise NotImplementedError


