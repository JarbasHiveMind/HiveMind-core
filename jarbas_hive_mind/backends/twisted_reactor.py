from autobahn.twisted.websocket import WebSocketServerProtocol, \
    WebSocketServerFactory, WebSocketClientFactory, \
    WebSocketClientProtocol
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.internet.error import ReactorNotRunning
from ovos_utils.log import LOG
from jarbas_hive_mind.backends.base import HiveMindAbstractListener, HiveMindAbstractConnection
from twisted.internet import reactor, ssl


class HiveMindTwistedConnection(HiveMindAbstractConnection):
    def run(self):
        if self._secure:
            contextFactory = ssl.ClientContextFactory()
            reactor.connectSSL(self.host, self.port, self.ws, contextFactory)
        else:
            reactor.connectTCP(self.host, self.port, self.ws)
        if not reactor.running and self._autorun:
            try:
                reactor.run()
            except Exception as e:
                LOG.exception(e)

    def close(self):
        if reactor.running:
            reactor.stop()


class HiveMindTwistedListener(HiveMindAbstractListener):

    def run(self):
        if self._use_ssl:
            # SSL server context: load server key and certificate
            contextFactory = ssl.DefaultOpenSSLContextFactory(self._ssl_key,
                                                              self._ssl_cert)
            reactor.listenSSL(self.port, self.factory, contextFactory)
        else:
            reactor.listenTCP(self.port, self.factory)

        if not reactor.running and self._autorun:
            try:
                reactor.run()
            except Exception as e:
                LOG.exception(e)

    def stop(self):
        try:
            reactor.stop()
        except ReactorNotRunning:
            LOG.info("twisted reactor stopped")
        except Exception as e:
            try:
                reactor.callFromThread(reactor.stop)
                for p in reactor.getDelayedCalls():
                    if p.active():
                        p.cancel()
            except Exception as e:
                LOG.error(e)
