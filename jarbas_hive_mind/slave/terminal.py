from jarbas_utils.log import LOG
from autobahn.twisted.websocket import WebSocketClientFactory, \
    WebSocketClientProtocol
from twisted.internet.protocol import ReconnectingClientFactory
from jarbas_hive_mind.exceptions import UnauthorizedKeyError
from jarbas_hive_mind.utils import encrypt_as_json, decrypt_from_json
import json

platform = "HiveMindTerminalv0.2"


class HiveMindTerminalProtocol(WebSocketClientProtocol):

    def onConnect(self, response):
        LOG.info("HiveMind connected: {0}".format(response.peer))
        self.factory.client = self
        self.factory.status = "connected"

    def onOpen(self):
        LOG.info("HiveMind websocket connection open. ")

    def onMessage(self, payload, isBinary):
        if not isBinary:
            payload = self.decode(payload)
            LOG.info("[MESSAGE] " + payload)
        else:
            LOG.debug("[BINARY MESSAGE]")

    def onClose(self, wasClean, code, reason):
        LOG.warning("HiveMind websocket connection closed: {0}".format(reason))
        self.factory.client = None
        self.factory.status = "disconnected"
        if "WebSocket connection upgrade failed" in reason:
            # key rejected
            LOG.error("Key rejected")
            raise UnauthorizedKeyError

    def decode(self, payload):
        payload = payload.decode("utf-8")
        if self.factory.crypto_key:
            payload = decrypt_from_json(self.factory.crypto_key, payload)
        return payload

    def sendMessage(self,
                    payload,
                    isBinary=False,
                    fragmentSize=None,
                    sync=False,
                    doNotCompress=False):
        if self.factory.crypto_key and not isBinary:
            payload = encrypt_as_json(self.factory.crypto_key, payload)
        if isinstance(payload, str):
            payload = bytes(payload, encoding="utf-8")
        super().sendMessage(payload, isBinary, fragmentSize=fragmentSize,
                            sync=sync, doNotCompress=doNotCompress)


class HiveMindTerminal(WebSocketClientFactory, ReconnectingClientFactory):
    protocol = HiveMindTerminalProtocol

    def __init__(self, crypto_key=None, *args, **kwargs):
        super(HiveMindTerminal, self).__init__(*args, **kwargs)
        self.status = "disconnected"
        self.client = None
        self.crypto_key = crypto_key

    # websocket handlers
    def clientConnectionFailed(self, connector, reason):
        LOG.error("HiveMind connection failed: " + str(
            reason) + " .. retrying ..")
        self.status = "disconnected"
        self.retry(connector)

    def clientConnectionLost(self, connector, reason):
        LOG.error("HiveMind connection lost: " + str(
            reason) + " .. retrying ..")
        self.status = "disconnected"
        self.retry(connector)

