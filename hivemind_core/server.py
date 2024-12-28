import os
import os.path
import random
from os import makedirs
from os.path import exists, join
from socket import gethostname
from typing import Optional, Tuple
import asyncio

from tornado import ioloop
from tornado.platform.asyncio import AnyThreadEventLoopPolicy
import pybase64
from OpenSSL import crypto
from ovos_bus_client.session import Session
from ovos_utils.log import LOG
from ovos_utils.xdg_utils import xdg_data_home
from poorman_handshake import PasswordHandShake
from tornado import web
from tornado.websocket import WebSocketHandler

from hivemind_bus_client.message import HiveMessageType
from hivemind_core.protocol import (
    HiveMindListenerProtocol,
    HiveMindClientConnection,
    HiveMindNodeType, NetworkProtocol
)


class HiveMindWebsocketProtocol(NetworkProtocol):
    """
    WebSocket handler for managing HiveMind client connections.

    Attributes:
        hm_protocol (Optional[HiveMindListenerProtocol]): The protocol instance for handling HiveMind messages.
    """
    hm_protocol: Optional[HiveMindListenerProtocol] = None


    def run(self):

        asyncio.set_event_loop_policy(AnyThreadEventLoopPolicy())
        HiveMindTornadoWebSocket.loop = ioloop.IOLoop.current()
        HiveMindTornadoWebSocket.hm_protocol = self.hm_protocol

        ssl = self.config.get("ssl", False)
        cert_dir: str = self.config.get("cert_dir") or f"{xdg_data_home()}/hivemind"
        cert_name: str = self.config.get("cert_name") or "hivemind"
        host = self.config.get("host") or self.identity.default_master or "0.0.0.0"
        host = host.split("://")[-1]
        port = int(self.config.get("port") or self.identity.default_port or 5678)

        routes: list = [("/", HiveMindTornadoWebSocket)]
        application = web.Application(routes)
        if ssl:
            cert_file = f"{cert_dir}/{cert_name}.crt"
            key_file = f"{cert_dir}/{cert_name}.key"
            if not os.path.isfile(key_file):
                LOG.info(f"generating self-signed SSL certificate")
                cert_file, key_file = self.create_self_signed_cert(cert_dir, cert_name)
            LOG.debug("using ssl key at " + key_file)
            LOG.debug("using ssl certificate at " + cert_file)
            ssl_options = {"certfile": cert_file, "keyfile": key_file}

            LOG.info("wss listener started")
            application.listen(port, host, ssl_options=ssl_options)
        else:
            LOG.info("ws listener started")
            application.listen(port, host)

        HiveMindTornadoWebSocket.loop.start()  # blocking

    @staticmethod
    def create_self_signed_cert(
            cert_dir: str = f"{xdg_data_home()}/hivemind",
            name: str = "hivemind"
    ) -> Tuple[str, str]:
        """
        Create a self-signed certificate and key pair if they do not already exist.

        Args:
            cert_dir (str): The directory where the certificate and key will be stored.
            name (str): The base name for the certificate and key files.

        Returns:
            Tuple[str, str]: The paths to the created certificate and key files.
        """
        CERT_FILE = name + ".crt"
        KEY_FILE = name + ".key"
        cert_path = join(cert_dir, CERT_FILE)
        key_path = join(cert_dir, KEY_FILE)
        makedirs(cert_dir, exist_ok=True)

        if not exists(join(cert_dir, CERT_FILE)) or not exists(join(cert_dir, KEY_FILE)):
            # create a key pair
            k = crypto.PKey()
            k.generate_key(crypto.TYPE_RSA, 2048)

            # Create a self-signed certificate
            cert = crypto.X509()
            cert.get_subject().C = "PT"
            cert.get_subject().ST = "Europe"
            cert.get_subject().L = "Mountains"
            cert.get_subject().O = "Jarbas AI"
            cert.get_subject().OU = "Powered by HiveMind"
            cert.get_subject().CN = gethostname()
            cert.set_serial_number(random.randint(0, 2000))
            cert.gmtime_adj_notBefore(0)
            cert.gmtime_adj_notAfter(10 * 365 * 24 * 60 * 60)
            cert.set_issuer(cert.get_subject())
            cert.set_pubkey(k)
            # TODO: Don't use SHA1
            cert.sign(k, "sha1")

            open(cert_path, "wb").write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
            open(key_path, "wb").write(crypto.dump_privatekey(crypto.FILETYPE_PEM, k))

        return cert_path, key_path


class HiveMindTornadoWebSocket(WebSocketHandler):
    """
    WebSocket handler for managing HiveMind client connections.

    Attributes:
        hm_protocol (Optional[HiveMindListenerProtocol]): The protocol instance for handling HiveMind messages.
    """
    hm_protocol = None

    @staticmethod
    def decode_auth(auth: str) -> Tuple[str, str]:
        """
        Decode the base64 encoded authorization string.

        Args:
            auth (str): The base64 encoded authorization string.

        Returns:
            Tuple[str, str]: The decoded username and key.
        """
        userpass_encoded = bytes(auth, encoding="utf-8")
        userpass_decoded = pybase64.b64decode(userpass_encoded).decode("utf-8")
        name, key = userpass_decoded.split(":")
        return name, key

    def on_message(self, message: str) -> None:
        """
        Handle incoming messages from the WebSocket.

        Args:
            message (str): The incoming message.
        """
        message = self.client.decode(message)
        if (
                message.msg_type == HiveMessageType.BUS
                and message.payload.msg_type == "recognizer_loop:b64_audio"
        ):
            LOG.info(f"Received {self.client.peer} sent base64 audio for STT")
        else:
            LOG.info(f"Received {self.client.peer} message: {message}")
        self.hm_protocol.handle_message(message, self.client)

    def open(self) -> None:
        """
        Handle a new client connection and perform authorization.
        """
        auth = self.request.uri.split("/?authorization=")[-1]
        useragent, key = self.decode_auth(auth)
        LOG.info(f"Authorizing client - {useragent}:{key}")

        def do_send(payload: str, is_bin: bool):
            self.loop.install()  # TODO is this needed?
            self.write_message(payload, is_bin)

        def do_disconnect():
            self.loop.install()  # TODO is this needed?
            self.close()

        self.client = HiveMindClientConnection(
            key=key,
            disconnect=do_disconnect,
            send_msg=do_send,
            sess=Session(session_id="default"),  # will be re-assigned once client sends handshake
            name=useragent,
            hm_protocol=self.hm_protocol
        )
        self.hm_protocol.db.sync()
        user = self.hm_protocol.db.get_client_by_api_key(key)

        if not user:
            LOG.error("Client provided an invalid api key")
            self.hm_protocol.handle_invalid_key_connected(self.client)
            self.close()
            return

        self.client.name = f"{useragent}::{user.client_id}::{user.name}"
        self.client.crypto_key = user.crypto_key
        self.client.msg_blacklist = user.message_blacklist or []
        self.client.skill_blacklist = user.skill_blacklist or []
        self.client.intent_blacklist = user.intent_blacklist or []
        self.client.allowed_types = user.allowed_types
        self.client.can_broadcast = user.can_broadcast
        self.client.can_propagate = user.can_propagate
        self.client.can_escalate = user.can_escalate
        if user.password:
            # pre-shared password to derive aes_key
            self.client.pswd_handshake = PasswordHandShake(user.password)

        self.client.node_type = HiveMindNodeType.NODE  # TODO . placeholder

        if (
                not self.client.crypto_key
                and not self.hm_protocol.handshake_enabled
                and self.hm_protocol.require_crypto
        ):
            LOG.error(
                "No pre-shared crypto key for client and handshake disabled, "
                "but configured to require crypto!"
            )
            # clients requiring handshake support might fail here
            self.hm_protocol.handle_invalid_protocol_version(self.client)
            self.close()
            return

        self.hm_protocol.handle_new_client(self.client)
        # self.write_message(Message("connected").serialize())

    def on_close(self):
        LOG.info(f"disconnecting client: {self.client.peer}")
        self.hm_protocol.handle_client_disconnected(self.client)

    def check_origin(self, origin) -> bool:
        return True
