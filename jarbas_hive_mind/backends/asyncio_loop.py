from autobahn.asyncio.websocket import WebSocketServerProtocol, \
    WebSocketServerFactory, WebSocketClientFactory, \
    WebSocketClientProtocol
import asyncio
import ssl
from jarbas_hive_mind.backends.base import HiveMindAbstractListener, HiveMindAbstractConnection
from ovos_utils.log import LOG


class HiveMindAsyncioConnection(HiveMindAbstractConnection):
    def run(self):
        self.loop = asyncio.get_event_loop()
        if self.is_secure:
            ssl_context = ssl.create_default_context()
            if self.accept_self_signed:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            coro = self.loop.create_connection(self.ws, self.host,
                                               self.port, ssl=ssl_context)
        else:
            coro = self.loop.create_connection(self.ws, self.host, self.port)
        self.loop.run_until_complete(coro)
        self.loop.run_forever()
        self.loop.close()

    def close(self):
        if self.loop:
            self.loop.close()


class HiveMindAsyncioListener(HiveMindAbstractListener):
    def run(self):
        self.loop = asyncio.get_event_loop()
        if self.is_secure:
            ssl_context = ssl.create_default_context()
            if self.accept_self_signed:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            ssl_context.load_cert_chain(self.ssl_cert, self.ssl_key)

            coro = self.loop.create_server(self.factory, self.host,
                                           self.port, ssl=ssl_context)
            LOG.info("HiveMind Listening: " + self.address)
        else:
            coro = self.loop.create_server(self.factory, self.host, self.port)
            LOG.info("HiveMind Listening (UNSECURED): " + self.address)

        self.server = self.loop.run_until_complete(coro)
        self.loop.run_forever()
        self.stop()

    def stop(self):
        self.server.close()
        self.loop.close()

