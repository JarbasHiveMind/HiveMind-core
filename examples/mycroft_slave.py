import base64
from twisted.internet import reactor, ssl
from jarbas_hive_mind.slave import JarbasDrone, JarbasDroneProtocol, platform


def connect_to_hivemind(host="127.0.0.1", port=5678, name="Jarbas Drone",
                        key="drone_key", useragent=platform, bus=None):
    authorization = bytes(name + ":" + key, encoding="utf-8")
    usernamePasswordDecoded = authorization
    key = base64.b64encode(usernamePasswordDecoded)
    headers = {'authorization': key}
    address = u"wss://" + host + u":" + str(port)
    factory = JarbasDrone(bus=bus, headers=headers,
                          useragent=useragent)
    factory.protocol = JarbasDroneProtocol
    contextFactory = ssl.ClientContextFactory()
    reactor.connectSSL(host, port, factory, contextFactory)
    reactor.run()


if __name__ == '__main__':
    # TODO arg parse
    connect_to_hivemind()
