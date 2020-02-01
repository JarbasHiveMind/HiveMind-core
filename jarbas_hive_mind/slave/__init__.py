import json
from threading import Thread

from autobahn.twisted.websocket import WebSocketClientFactory, \
    WebSocketClientProtocol
from twisted.internet.protocol import ReconnectingClientFactory

from jarbas_utils.log import LOG as logger
from jarbas_utils.messagebus import Message, get_mycroft_bus

platform = "Jarbas Drone"


class JarbasDroneProtocol(WebSocketClientProtocol):

    def onConnect(self, response):
        logger.info("Server connected: {0}".format(response.peer))
        self.factory.bus.emit(Message("hive.mind.connected",
                                      {"server_id": response.headers[
                                              "server"]}))
        self.factory.client = self
        self.factory.status = "connected"

    def onOpen(self):
        logger.info("WebSocket connection open. ")
        self.factory.bus.emit(Message("hive.mind.websocket.open"))

    def onMessage(self, payload, isBinary):
        logger.info("status: " + self.factory.status)
        if not isBinary:
            payload = payload.decode("utf-8")
            data = {"payload": payload, "isBinary": isBinary}
        else:
            data = {"payload": None, "isBinary": isBinary}
        self.factory.bus.emit(Message("hive.mind.message.received",
                                      data))

    def onClose(self, wasClean, code, reason):
        logger.info("WebSocket connection closed: {0}".format(reason))
        self.factory.bus.emit(Message("hive.mind.connection.closed",
                                      {"wasClean": wasClean,
                                           "reason": reason,
                                           "code": code}))
        self.factory.client = None
        self.factory.status = "disconnected"

    def serialize_message(self, message):
        # convert a Message object into raw data that can be sent over
        # websocket
        if hasattr(message, 'serialize'):
            return message.serialize()
        else:
            return json.dumps(message.__dict__)


class JarbasDrone(WebSocketClientFactory, ReconnectingClientFactory):
    protocol = JarbasDroneProtocol

    def __init__(self, bus=None, *args, **kwargs):
        super(JarbasDrone, self).__init__(*args, **kwargs)
        self.client = None
        self.status = "disconnected"
        # mycroft_ws
        self.bus = bus or get_mycroft_bus()
        self.register_mycroft_messages()

    # initialize methods
    def register_mycroft_messages(self):
        self.bus.on("hive.mind.message.received",
                    self.handle_receive_server_message)
        self.bus.on("hive.mind.message.send",
                    self.handle_send_server_message)

    def shutdown(self):
        self.bus.remove("hive.mind.message.received",
                        self.handle_receive_server_message)
        self.bus.remove("hive.mind.message.send",
                        self.handle_send_server_message)

    # websocket handlers
    def clientConnectionFailed(self, connector, reason):
        logger.info(
            "Client connection failed: " + str(reason) + " .. retrying ..")
        self.status = "disconnected"
        self.retry(connector)

    def clientConnectionLost(self, connector, reason):
        logger.info(
            "Client connection lost: " + str(reason) + " .. retrying ..")
        self.status = "disconnected"
        self.retry(connector)

    # mycroft handlers
    def handle_receive_server_message(self, message):
        server_msg = message.data.get("payload")
        is_file = message.data.get("isBinary")
        if is_file:
            # TODO received file
            pass
        else:
            # forward server message to internal bus
            message = Message.deserialize(server_msg)
            self.bus.emit(message)

    def handle_send_server_message(self, message):
        server_msg = message.data.get("payload")
        is_file = message.data.get("isBinary")
        if is_file:
            # TODO send file
            pass
        else:
            # send message to server
            server_msg = Message.deserialize(server_msg)
            server_msg.context["platform"] = platform
            self.sendMessage(server_msg.type, server_msg.data,
                             server_msg.context)

    def sendRaw(self, data):
        if self.client is None:
            logger.error("Client is none")
            return
        self.client.sendMessage(data, isBinary=True)

    def sendMessage(self, type, data, context=None):
        if self.client is None:
            logger.error("Client is none")
            return
        if context is None:
            context = {}
        msg = self.client.serialize_message(Message(type, data, context))
        self.client.sendMessage(msg, isBinary=False)
        self.bus.emit(Message("hive.mind.message.sent",
                              {"type": type,
                               "data": data,
                               "context": context,
                               "raw": msg}))


