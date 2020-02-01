from jarbas_hive_mind.master import JarbasMind, JarbasMindProtocol
from twisted.internet import reactor, ssl
from jarbas_hive_mind.settings import CERTS_PATH, DEFAULT_SSL_CRT, \
    DEFAULT_SSL_KEY, DEFAULT_PORT, USE_SSL
from jarbas_hive_mind.utils import create_self_signed_cert
from jarbas_utils.log import LOG
from os.path import exists


def start_mind(config=None, bus=None):
    # server
    config = config or {}
    host = config.get("host", "0.0.0.0")
    port = config.get("port", DEFAULT_PORT)
    # TODO non-ssl support
    use_ssl = config.get("ssl", USE_SSL)
    max_connections = config.get("max_connections", -1)
    address = u"wss://" + str(host) + u":" + str(port)
    cert = config.get("cert_file", DEFAULT_SSL_CRT)
    key = config.get("key_file", DEFAULT_SSL_KEY)

    factory = JarbasMind(bus=bus)
    factory.protocol = JarbasMindProtocol
    if max_connections >= 0:
        factory.setProtocolOptions(maxConnections=max_connections)

    if not exists(key) or not exists(cert):
        LOG.warning("ssl keys dont exist, creating self signed")
        name = key.split("/")[-1].replace(".key", "")
        create_self_signed_cert(CERTS_PATH, name)
        cert = CERTS_PATH + "/" + name + ".crt"
        key = CERTS_PATH + "/" + name + ".key"
        LOG.info("key created at: " + key)
        LOG.info("crt created at: " + cert)
        # update config with new keys
        config["cert_file"] = cert
        config["key_file"] = key
        # factory.config_update({"mind": config}, True)

    # SSL server context: load server key and certificate
    contextFactory = ssl.DefaultOpenSSLContextFactory(key, cert)

    reactor.listenSSL(port, factory, contextFactory)
    print("Starting mind: ", address)
    reactor.run()


if __name__ == '__main__':
    start_mind()
