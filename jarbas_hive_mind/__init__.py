import base64
from twisted.internet import reactor, ssl
from jarbas_hive_mind.master import HiveMind, HiveMindProtocol
from jarbas_hive_mind.configuration import CONFIGURATION
from jarbas_hive_mind.utils import create_self_signed_cert
from jarbas_utils.log import LOG
from jarbas_utils.messagebus import get_mycroft_bus


class HiveMindConnection:
    def __init__(self, host="127.0.0.1", port=5678):
        self.host = host
        self.port = port

    @property
    def address(self):
        return "wss://" + self.host + u":" + str(self.port)

    @staticmethod
    def get_headers(name, key):
        # Note that keys can be shared across users
        # name is not used for auth
        authorization = bytes(name + ":" + key, encoding="utf-8")
        key = base64.b64encode(authorization)
        headers = {'authorization': key}
        return headers

    def secure_connect(self, connection):
        contextFactory = ssl.ClientContextFactory()
        reactor.connectSSL(self.host, self.port, connection, contextFactory)
        reactor.run()


class HiveMindListener:
    def __init__(self, port=5678, max_cons=-1, bus=None):
        self.host = "0.0.0.0"
        self.port = port
        self.max_cons = max_cons

        # TODO read config for bus options
        self.bus = bus or get_mycroft_bus()

    @property
    def address(self):
        return "wss://" + self.host + u":" + str(self.port)

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

    def secure_listen(self, key, cert):
        # SSL server context: load server key and certificate
        contextFactory = ssl.DefaultOpenSSLContextFactory(key, cert)

        factory = HiveMind(bus=self.bus)
        factory.protocol = HiveMindProtocol
        if self.max_cons >= 0:
            factory.setProtocolOptions(maxConnections=self.max_cons)

        reactor.listenSSL(self.port, factory, contextFactory)
        LOG.info("HiveMind Listening: " + self.address)
        reactor.run()


if __name__ == '__main__':

    def connect_to_hivemind(host="127.0.0.1",
                            port=5678, name="Jarbas Dummy Terminal",
                            key="cli_key", useragent="JarbasDummyTerminalV0.1"):
        con = HiveMindConnection(host, port)

        from jarbas_hive_mind.slave.terminal import HiveMindTerminal
        terminal = HiveMindTerminal(con.address,
                                    headers=con.get_headers(name, key),
                                    useragent=useragent)

        con.secure_connect(terminal)

    # client
    # connect_to_hivemind()
