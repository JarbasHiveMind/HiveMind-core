from jarbas_utils.log import LOG
from autobahn.twisted.websocket import WebSocketClientFactory, \
    WebSocketClientProtocol
from twisted.internet.protocol import ReconnectingClientFactory

platform = "HiveMindTerminalv0.1"


class HiveMindTerminalProtocol(WebSocketClientProtocol):

    def onConnect(self, response):
        LOG.info("HiveMind connected: {0}".format(response.peer))
        self.factory.client = self
        self.factory.status = "connected"

    def onOpen(self):
        LOG.info("HiveMind websocket connection open. ")

    def onMessage(self, payload, isBinary):
        if not isBinary:
            LOG.info("[MESSAGE] " + payload)
        else:
            LOG.debug("[BINARY MESSAGE]")

    def onClose(self, wasClean, code, reason):
        LOG.info("HiveMind websocket connection closed: {0}".format(reason))
        self.factory.client = None
        self.factory.status = "disconnected"
        if "Internalservererror:InvalidAPIkey" in reason:
            LOG.error("invalid user:key provided")
            raise ConnectionAbortedError("invalid user:key provided")


class HiveMindTerminal(WebSocketClientFactory, ReconnectingClientFactory):
    protocol = HiveMindTerminalProtocol

    def __init__(self, *args, **kwargs):
        super(HiveMindTerminal, self).__init__(*args, **kwargs)
        self.status = "disconnected"
        self.client = None

    # websocket handlers
    def clientConnectionFailed(self, connector, reason):
        LOG.info("HiveMind connection failed: " + str(
            reason) + " .. retrying ..")
        self.status = "disconnected"
        self.retry(connector)

    def clientConnectionLost(self, connector, reason):
        LOG.info("HiveMind connection lost: " + str(
            reason) + " .. retrying ..")
        self.status = "disconnected"
        self.retry(connector)

