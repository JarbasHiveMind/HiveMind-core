import dataclasses
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Union, List, Optional, Callable, Literal

import pybase64
from ovos_bus_client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG
from hivemind_core.config import get_server_config
from hivemind_bus_client.identity import NodeIdentity
from hivemind_bus_client.message import HiveMessage, HiveMessageType, HiveMindBinaryPayloadType
from hivemind_bus_client.serialization import decode_bitstring, get_bitstring
from hivemind_bus_client.encryption import (SupportedEncodings, SupportedCiphers,
                                            decrypt_from_json, encrypt_as_json,
                                            decrypt_bin, encrypt_bin,
                                            _norm_encoding, _norm_cipher)
from hivemind_core.database import ClientDatabase
from hivemind_plugin_manager.protocols import AgentProtocol, BinaryDataHandlerProtocol, ClientCallbacks
from poorman_handshake import HandShake, PasswordHandShake
from poorman_handshake.asymmetric.utils import decrypt_RSA, load_RSA_key


class ProtocolVersion(IntEnum):
    ZERO = 0  # json only, no handshake, no binary
    ONE = 1  # handshake https://github.com/JarbasHiveMind/HiveMind-core/pull/29
    TWO = 2  # binary https://github.com/JarbasHiveMind/hivemind_websocket_client/pull/4


class HiveMindNodeType(str, Enum):
    CANDIDATE_NODE = "candidate"  # potential node, if it manages to connect...
    NODE = "node"  # anything connected to the hivemind is a "node"
    MIND = "mind"  # listening for connections and providing mycroft-core
    # (mycroft itself may be running in a different "mind")
    FAKECROFT = "fakecroft"  # a mind, that pretends to be running mycroft
    # but is actually using a different stack
    # (mycroft itself may be running in a different "mind")
    SLAVE = "slave"  # node that can be partially controlled by a "mind"
    TERMINAL = "terminal"  # user facing endpoint that connects to some Mind
    # and does not itself accept connections
    BRIDGE = "bridge"  # connects some external service to the hive

    # RESERVED
    HIVE = "hive"  # a collection of nodes
    MASTER_MIND = "master"  # the top level node, not connected to anything
    # but receiving connections


@dataclass
class HiveMindClientConnection:
    """represents a connection to the hivemind listener"""
    key: str
    send_msg: Callable[[str, bool], None]
    disconnect: Callable[[], None]

    sess: Session = dataclasses.field(default_factory=Session)  # unique session per client
    name: str = "AnonClient"
    node_type: HiveMindNodeType = HiveMindNodeType.CANDIDATE_NODE
    handshake: Optional[HandShake] = None
    pswd_handshake: Optional[PasswordHandShake] = None

    crypto_key: Optional[str] = None
    pub_key: Optional[str] = None  # TODO add field to database

    msg_blacklist: List[str] = field(
        default_factory=list
    )  # list of ovos message_type to never be sent to this client
    skill_blacklist: List[str] = field(
        default_factory=list
    )  # list of skill_id that can't match for this client
    intent_blacklist: List[str] = field(
        default_factory=list
    )  # list of skill_id:intent_name that can't match for this client
    allowed_types: List[str] = field(
        default_factory=list
    )  # list of ovos message_type to allow to be sent from this client
    binarize: bool = False
    site_id: str = "unknown"
    can_escalate: bool = True
    can_propagate: bool = True
    is_admin: bool = False
    last_seen: float = -1

    hm_protocol: Optional['HiveMindListenerProtocol'] = None

    cipher: Literal[SupportedCiphers] = SupportedCiphers.AES_GCM
    encoding: Literal[SupportedEncodings] = SupportedEncodings.JSON_HEX

    def __post_init__(self):
        self.handshake = self.handshake or HandShake(self.hm_protocol.identity.private_key)

    @property
    def peer(self) -> str:
        # friendly id that ovos components can use to refer to this connection
        # this is how ovos refers to connected nodes in message.context
        return f"{self.name}::{self.sess.session_id}"

    def send(self, message: HiveMessage):
        is_bin = message.msg_type == HiveMessageType.BINARY
        # TODO some cleaning around HiveMessage
        if not is_bin:
            if isinstance(message.payload, dict):
                _msg_type = message.payload.get("type")
            else:
                _msg_type = message.payload.msg_type

            if _msg_type in self.msg_blacklist:
                LOG.debug(
                    f"message type {_msg_type} is blacklisted for {self.peer}"
                )
                return
            elif message.msg_type == HiveMessageType.BUS:
                LOG.debug(f"mycroft_type {_msg_type}")

        LOG.debug(f"sending to {self.peer}: {message.msg_type}")

        if self.crypto_key and message.msg_type not in [
            HiveMessageType.HANDSHAKE,
            HiveMessageType.HELLO,
        ]:
            if self.binarize or is_bin:
                payload = get_bitstring(hive_type=message.msg_type,
                                        payload=message.payload,
                                        hivemeta=message.metadata,
                                        binary_type=message.bin_type).bytes
                LOG.debug(f"unencrypted binary payload size: {len(payload)} bytes")
                payload = encrypt_bin(key=self.crypto_key, plaintext=payload, cipher=self.cipher)
                is_bin = True
            else:
                LOG.debug(f"unencrypted payload size: {len(message.payload.serialize())} bytes")
                payload = encrypt_as_json(
                    key=self.crypto_key, plaintext=message.serialize(),
                    cipher=self.cipher, encoding=self.encoding
                )  # json string
            LOG.debug(f"encrypted payload size: {len(payload)} bytes")
        else:
            payload = message.serialize()
            LOG.debug(f"sent unencrypted!")

        self.send_msg(payload, is_bin)

    def decode(self, payload: str) -> HiveMessage:
        if self.crypto_key:
            # handle binary encryption
            if isinstance(payload, bytes):
                payload = decrypt_bin(key=self.crypto_key, ciphertext=payload,
                                      cipher=self.cipher)
            # handle json encryption
            elif "ciphertext" in payload:
                payload = decrypt_from_json(key=self.crypto_key, ciphertext_json=payload,
                                            encoding=self.encoding, cipher=self.cipher)
            else:
                LOG.warning("Message was unencrypted")
                # TODO - some error if crypto is required
        else:
            pass  # TODO - reject anything except HELLO and HANDSHAKE

        if isinstance(payload, bytes):
            return decode_bitstring(payload)
        elif isinstance(payload, str):
            payload = json.loads(payload)
        return HiveMessage(**payload)

    def authorize(self, message: Message) -> bool:
        """parse the message being injected into ovos-core bus
        if this client is not authorized to inject it return False"""
        if message.msg_type not in self.allowed_types:
            return False

        # TODO check intent / skill that will trigger
        # for OVOS agent this is passed in Session and ignored during match
        # adding it here allows blocking the utterance completely instead
        # or adding a callback for specific agents to decide how to handle
        return True


@dataclass
class HiveMindListenerProtocol:
    agent_protocol: Optional[AgentProtocol] = None
    binary_data_protocol: Optional[BinaryDataHandlerProtocol] = None
    peer: str = "master:0.0.0.0"

    require_crypto: bool = True  # throw error if crypto key not available
    handshake_enabled: bool = True  # generate a key per session if not pre-shared
    identity: NodeIdentity = dataclasses.field(default_factory=NodeIdentity)
    db: ClientDatabase = dataclasses.field(default_factory=ClientDatabase)
    callbacks: ClientCallbacks = dataclasses.field(default_factory=ClientCallbacks)

    # below are optional callbacks to handle payloads
    # receives the payload + HiveMindClient that sent it
    escalate_callback = None  # slave asked to escalate payload
    illegal_callback = None  # slave asked to broadcast payload (illegal action)
    propagate_callback = None  # slave asked to propagate payload
    broadcast_callback = None  # slave asked to broadcast payload
    agent_bus_callback = None  # slave asked to inject payload into mycroft bus
    shared_bus_callback = None  # passive sharing of slave device bus (info)

    clients = {}  # class object

    def __post_init__(self):
        self.agent_protocol.hm_protocol = self
        if not self.binary_data_protocol:
            # just logs received messages
            self.binary_data_protocol = BinaryDataHandlerProtocol(hm_protocol=self,
                                                                  agent_protocol=self.agent_protocol)
        else:
            self.binary_data_protocol.hm_protocol = self

    def get_bus(self, client: HiveMindClientConnection) -> Union[FakeBus, MessageBusClient]:
        # allow subclasses to use dedicated bus per client
        return self.agent_protocol.bus

    def handle_new_client(self, client: HiveMindClientConnection):
        try:
            self.callbacks.on_connect(client)
        except:
            LOG.exception("error on connect callback")

        try:  # let the binary protocol know about it
            self.binary_data_protocol.callbacks.on_connect(client)
        except:
            LOG.exception("error on connect binary callback")

        try:  # let the agent protocol know about it
            self.agent_protocol.callbacks.on_connect(client)
        except:
            LOG.exception("error on connect agent callback")

        LOG.debug(f"new client: {client.peer}")
        message = Message(
            "hive.client.connect",
            {"key": client.key,
             "session_id": client.sess.session_id},
            {"source": client.peer},
        )

        bus = self.get_bus(client)
        bus.emit(message)

        min_version = (
            ProtocolVersion.ONE
            if client.crypto_key is None and self.require_crypto
            else ProtocolVersion.ZERO
        )
        max_version = ProtocolVersion.ONE

        msg = HiveMessage(
            HiveMessageType.HELLO,
            payload={
                "pubkey": client.handshake.pubkey,
                # allows any node to verify messages are signed with this
                "peer": client.peer,  # this identifies the connected client in ovos message.context
                "node_id": self.peer
            },
        )
        LOG.debug(f"saying HELLO to: {client.peer}")
        client.send(msg)

        needs_handshake = not client.crypto_key and self.handshake_enabled

        cfg = get_server_config()
        allowed_ciphers = cfg.get("allowed_ciphers") or [SupportedCiphers.AES_GCM]
        allowed_encodings = cfg.get("allowed_encodings") or list(SupportedEncodings)

        # request client to start handshake (by sending client pubkey)
        payload = {
            "handshake": needs_handshake,  # tell the client it must do a handshake or connection will be dropped
            "min_protocol_version": min_version,
            "max_protocol_version": max_version,
            "binarize": cfg.get("binarize", False),  # report we support the binarization scheme
            "preshared_key": client.crypto_key
                             is not None,  # do we have a pre-shared key (V0 proto)
            "password": client.pswd_handshake
                        is not None,  # is password available (V1 proto, replaces pre-shared key)
            "crypto_required": self.require_crypto,  # do we allow unencrypted payloads
            "encodings": allowed_encodings,
            "ciphers": allowed_ciphers
        }
        msg = HiveMessage(HiveMessageType.HANDSHAKE, payload)
        LOG.debug(f"starting {client.peer} HANDSHAKE: {payload}")
        client.send(msg)
        # if client is in protocol V1 -> self.handle_handshake_message
        # clients can rotate their pubkey or session_key by sending a new handshake

    def update_last_seen(self, client: HiveMindClientConnection):
        """track timestamps of last client interaction"""
        with self.db:
            user = self.db.get_client_by_api_key(client.key)
            user.last_seen = time.time()
            LOG.debug(f"updated last seen timestamp: {client.key} - {user.last_seen}")
            self.db.update_item(user)

    def handle_client_disconnected(self, client: HiveMindClientConnection):
        try:
            self.callbacks.on_disconnect(client)
        except:
            LOG.exception("error on disconnect callback")

        try:  # let the binary protocol know about it
            self.binary_data_protocol.callbacks.on_disconnect(client)
        except:
            LOG.exception("error on disconnect binary callback")

        try:  # let the agent protocol know about it
            self.agent_protocol.callbacks.on_disconnect(client)
        except:
            LOG.exception("error on disconnect agent callback")

        if client.peer in self.clients:
            self.clients.pop(client.peer)
        client.disconnect()
        message = Message(
            "hive.client.disconnect",
            {"key": client.key},
            {"source": client.peer, "session": client.sess.serialize()},
        )
        bus = self.get_bus(client)
        bus.emit(message)

    def handle_invalid_key_connected(self, client: HiveMindClientConnection):
        try:
            self.callbacks.on_invalid_key(client)
        except:
            LOG.exception("error on invalid_key callback")

        try:  # let the binary protocol know about it
            self.binary_data_protocol.callbacks.on_invalid_key(client)
        except:
            LOG.exception("error on invalid_key binary callback")

        try:  # let the agent protocol know about it
            self.agent_protocol.callbacks.on_invalid_key(client)
        except:
            LOG.exception("error on invalid_key agent callback")

        LOG.error("Client provided an invalid api key")
        message = Message(
            "hive.client.connection.error",
            {"error": "invalid access key", "peer": client.peer},
            {"source": client.peer},
        )
        bus = self.get_bus(client)
        bus.emit(message)

    def handle_invalid_protocol_version(self, client: HiveMindClientConnection):
        try:
            self.callbacks.on_invalid_protocol(client)
        except:
            LOG.exception("error on invalid_protocol callback")

        try:  # let the binary protocol know about it
            self.binary_data_protocol.callbacks.on_invalid_protocol(client)
        except:
            LOG.exception("error on invalid_protocol binary callback")

        try:  # let the agent protocol know about it
            self.agent_protocol.callbacks.on_invalid_protocol(client)
        except:
            LOG.exception("error on invalid_protocol agent callback")

        LOG.error("Client does not satisfy protocol requirements")
        message = Message(
            "hive.client.connection.error",
            {"error": "protocol error", "peer": client.peer},
            {"source": client.peer},
        )
        bus = self.get_bus(client)
        bus.emit(message)

    def handle_message(self, message: HiveMessage, client: HiveMindClientConnection):
        """
        message (HiveMessage): HiveMind message object

        Process message from client, decide what to do internally here
        """
        LOG.debug(f"message: {message}")
        # update internal peer ID
        message.update_source_peer(client.peer)

        message.update_hop_data()

        if message.msg_type == HiveMessageType.HANDSHAKE:
            self.handle_handshake_message(message, client)
        elif message.msg_type == HiveMessageType.HELLO:
            self.handle_hello_message(message, client)

        # mycroft Message handlers
        elif message.msg_type == HiveMessageType.BUS:
            self.handle_bus_message(message, client)
        elif message.msg_type == HiveMessageType.SHARED_BUS:
            self.handle_client_shared_bus(message.payload, client)

        # HiveMessage handlers
        elif message.msg_type == HiveMessageType.PROPAGATE:
            self.handle_propagate_message(message, client)
        elif message.msg_type == HiveMessageType.BROADCAST:
            self.handle_broadcast_message(message, client)
        elif message.msg_type == HiveMessageType.ESCALATE:
            self.handle_escalate_message(message, client)
        elif message.msg_type == HiveMessageType.INTERCOM:
            self.handle_intercom_message(message, client)
        elif message.msg_type == HiveMessageType.BINARY:
            self.handle_binary_message(message, client)
        else:
            self.handle_unknown_message(message, client)

        self.update_last_seen(client)

    # HiveMind protocol messages -  from slave -> master
    def handle_unknown_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        """message handler for non default message types, subclasses can
        handle their own types here

        message (HiveMessage): HiveMind message object
        """

    def handle_binary_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        assert message.msg_type == HiveMessageType.BINARY
        bin_data = message.payload
        if message.bin_type == HiveMindBinaryPayloadType.RAW_AUDIO:
            sr = message.metadata.get("sample_rate", 16000)
            sw = message.metadata.get("sample_width", 2)
            self.binary_data_protocol.handle_microphone_input(bin_data, sr, sw, client)
        elif message.bin_type == HiveMindBinaryPayloadType.STT_AUDIO_TRANSCRIBE:
            lang = message.metadata.get("lang")
            sr = message.metadata.get("sample_rate", 16000)
            sw = message.metadata.get("sample_width", 2)
            self.binary_data_protocol.handle_stt_transcribe_request(bin_data, sr, sw, lang, client)
        elif message.bin_type == HiveMindBinaryPayloadType.STT_AUDIO_HANDLE:
            lang = message.metadata.get("lang")
            sr = message.metadata.get("sample_rate", 16000)
            sw = message.metadata.get("sample_width", 2)
            self.binary_data_protocol.handle_stt_handle_request(bin_data, sr, sw, lang, client)
        elif message.bin_type == HiveMindBinaryPayloadType.TTS_AUDIO:
            lang = message.metadata.get("lang")
            utt = message.metadata.get("utterance")
            file_name = message.metadata.get("file_name")
            self.binary_data_protocol.handle_receive_tts(bin_data, utt, lang, file_name, client)
        elif message.bin_type == HiveMindBinaryPayloadType.FILE:
            file_name = message.metadata.get("file_name")
            self.binary_data_protocol.handle_receive_file(bin_data, file_name, client)
        elif message.bin_type == HiveMindBinaryPayloadType.NUMPY_IMAGE:
            # TODO - convert to numpy array
            camera_id = message.metadata.get("camera_id")
            self.binary_data_protocol.handle_numpy_image(bin_data, camera_id, client)
        else:
            LOG.warning(f"Ignoring received untyped binary data: {len(bin_data)} bytes")

    def handle_handshake_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        LOG.debug("handshake received, generating session key")
        if "pubkey" in message.payload and client.handshake is not None:
            pub = message.payload.pop("pubkey")
            envelope_out = client.handshake.generate_handshake(pub)
            client.crypto_key = client.handshake.secret  # start using new key

            # client side
            # LOG.info("Received encryption key")
            # pub = "pubkey from HELLO message"
            # if pub:  # validate server from known trusted public key
            #   self.handshake.receive_and_verify(payload["envelope"], pub)
            # else:  # implicitly trust server
            #   self.handshake.receive_handshake(payload["envelope"], pub)
            # self.crypto_key = self.handshake.secret
        elif client.pswd_handshake is not None and "envelope" in message.payload:
            # sorted by preference from client
            encodings = message.payload.get("encodings") or [SupportedEncodings.JSON_HEX]
            encodings = [_norm_encoding(e) for e in encodings]
            ciphers = message.payload.get("ciphers") or [SupportedCiphers.AES_GCM]
            ciphers = [_norm_cipher(c) for c in ciphers]

            # allowed ciphers/encodings defined in config
            cfg = get_server_config()
            allowed_encodings = cfg.get("allowed_encodings") or list(SupportedEncodings)
            allowed_ciphers = cfg.get("allowed_ciphers") or [SupportedCiphers.AES_GCM]

            encodings = [e for e in encodings if e in allowed_encodings]
            ciphers = [c for c in ciphers if c in allowed_ciphers]
            if not ciphers or not encodings:
                LOG.warning("Client tried to connect with invalid cipher/encoding")
                # TODO - invalid handshake handler
                client.disconnect()
                return

            # from the allowed options, select the one the client prefers
            client.cipher = ciphers[0]
            client.encoding = encodings[0]
            client.binarize = message.payload.get("binarize", False)

            envelope = message.payload["envelope"]
            envelope_out = client.pswd_handshake.generate_handshake()
            client.pswd_handshake.receive_handshake(envelope)

            # if not client.pswd_handshake.receive_and_verify(envelope):
            #     # TODO - different handles for invalid access key / invalid password
            #     self.handle_invalid_key_connected(client)
            #     client.disconnect()
            #     return

            # key is derived safely from password in both sides
            # the handshake is validating both ends have the same password
            # the key is never actually transmitted
            client.crypto_key = client.pswd_handshake.secret

            # client side
            # LOG.info("Received password envelope")
            # self.pswd_handshake.receive_and_verify(payload["envelope"])
            # self.crypto_key = self.pswd_handshake.secret
        else:
            # TODO - invalid handshake handler
            client.disconnect()
            return

        msg = HiveMessage(HiveMessageType.HANDSHAKE,
                          {"envelope": envelope_out,
                           "encoding": client.encoding,
                           "cipher": client.cipher })
        client.send(msg)  # client can recreate crypto_key on his side now

    def handle_hello_message(self, message: HiveMessage, client: HiveMindClientConnection):
        LOG.debug("client Hello received, syncing personal session data")
        payload = message.payload
        if "session" in payload:
            client.sess = Session.deserialize(payload["session"])
        if "site_id" in payload:
            client.sess.site_id = client.site_id = payload["site_id"]
        if "pubkey" in payload:
            client.pub_key = payload["pubkey"]
            LOG.debug(f"client sent public key")
        else:
            LOG.warning(f"client did NOT send public key")

        LOG.debug(f"client site_id: {client.sess.site_id}")
        if client.sess.session_id != "default":
            LOG.debug(f"client session_id: {client.sess.session_id}")
            self.clients[client.peer] = client
        else:
            LOG.warning("client did not send a session after it's handshake")

    def handle_bus_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        # track any Session updates from client side
        sess = Session.from_message(message.payload)
        if client.sess.session_id == "default":
            LOG.warning(f"{client.peer} did not send a Session via handshake")
            if sess.session_id == "default":
                client.sess.session_id = str(uuid.uuid4())
                LOG.debug(f"Client session_id randomly generated: {client.sess.session_id}")
            else:
                client.sess.session_id = sess.session_id
                LOG.debug(f"Client session_id assigned via client first message: {client.sess.session_id}")
            self.clients[client.peer] = client

        if sess.session_id == "default":
            sess.session_id = client.sess.session_id
        if client.sess.session_id == sess.session_id:
            client.sess = sess
            LOG.debug(f"Client session updated from payload: {sess.serialize()}")

        self.handle_inject_agent_msg(message.payload, client)
        if self.agent_bus_callback:
            self.agent_bus_callback(message.payload)

    def handle_broadcast_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        """
        message (HiveMessage): HiveMind message object
        """
        payload = self._unpack_message(message, client)

        if not client.is_admin:
            LOG.warning("Received broadcast message from downstream, illegal action")
            if self.illegal_callback:
                self.illegal_callback(payload)
            # TODO kick client for misbehaviour so it stops doing that?
            return

        if self.broadcast_callback:
            self.broadcast_callback(payload)

        if message.payload.msg_type == HiveMessageType.INTERCOM:
            if self.handle_intercom_message(message.payload, client):
                return

        if message.payload.msg_type == HiveMessageType.BUS:
            # if the message targets our site_id, send it to internal bus
            site = message.target_site_id
            if site and site == self.identity.site_id:
                self.handle_bus_message(message.payload, client)

        # broadcast message to other peers
        payload = self._unpack_message(message, client)
        for peer in self.clients:
            if peer == client.peer:
                continue
            self.clients[peer].send(payload)

    def _unpack_message(self, message: HiveMessage, client: HiveMindClientConnection):
        # propagate message to other peers
        pload = message.payload
        # keep info about which nodes this message has been to
        pload.replace_route(message.route)
        pload.update_source_peer(self.peer)
        pload.remove_target_peer(client.peer)
        return pload

    def handle_propagate_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        """
        message (HiveMessage): HiveMind message object
        """
        LOG.debug("ROUTE: " + str(message.route))
        LOG.debug("PAYLOAD_TYPE: " + message.payload.msg_type)
        LOG.debug("PAYLOAD: " + str(message.payload.payload))

        payload = self._unpack_message(message, client)

        if not client.can_propagate:
            LOG.warning("Received propagate message from downstream, illegal action")
            if self.illegal_callback:
                self.illegal_callback(payload)
            # TODO kick client for misbehaviour so it stops doing that?
            return

        if self.propagate_callback:
            self.propagate_callback(payload)

        if message.payload.msg_type == HiveMessageType.INTERCOM:
            if self.handle_intercom_message(message.payload, client):
                return

        if message.payload.msg_type == HiveMessageType.BUS:
            # if the message targets our site_id, send it to internal bus
            site = message.target_site_id
            if site and site == self.identity.site_id:
                self.handle_bus_message(message.payload, client)

        # propagate message to other peers
        for peer in self.clients:
            if peer == client.peer:
                continue
            self.clients[peer].send(payload)

        # send to other masters
        message = Message(
            "hive.send.upstream",
            payload,
            {
                "destination": "hive",
                "source": self.peer,
                "session": client.sess.serialize(),
            },
        )
        bus = self.get_bus(client)
        bus.emit(message)

    def handle_escalate_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        """
        message (HiveMessage): HiveMind message object
        """
        LOG.info("Received escalate message from: " + client.peer)
        LOG.debug("ROUTE: " + str(message.route))
        LOG.debug("PAYLOAD_TYPE: " + message.payload.msg_type)
        LOG.debug("PAYLOAD: " + str(message.payload.payload))

        # unpack message
        payload = self._unpack_message(message, client)

        if not client.can_escalate:
            LOG.warning("Received escalate message from downstream, illegal action")
            if self.illegal_callback:
                self.illegal_callback(payload)
            # TODO kick client for misbehaviour so it stops doing that?
            return

        if self.escalate_callback:
            self.escalate_callback(payload)

        if message.payload.msg_type == HiveMessageType.INTERCOM:
            if self.handle_intercom_message(message.payload, client):
                return

        if message.payload.msg_type == HiveMessageType.BUS:
            # if the message targets our site_id, send it to internal bus
            site = message.target_site_id
            if site and site == self.identity.site_id:
                self.handle_bus_message(message.payload, client)

        # send to other masters
        message = Message(
            "hive.send.upstream",
            payload,
            {
                "destination": "hive",
                "source": self.peer,
                "session": client.sess.serialize(),
            },
        )
        bus = self.get_bus(client)
        bus.emit(message)

    def handle_intercom_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ) -> bool:

        # if the message targets us, send it to internal bus
        k = message.target_public_key
        if k and k != self.identity.public_key:
            # not for us
            return False

        pload = message.payload
        if isinstance(pload, dict) and "ciphertext" in pload:
            try:
                ciphertext = pybase64.b64decode(pload["ciphertext"])
                signature = pybase64.b64decode(pload["signature"])

                # TODO - allow verifying, we need to store trusted pubkeys before this can be done
                # pub = ""
                # verified = verify_RSA(pub, ciphertext, signature)

                private_key = load_RSA_key(self.identity.private_key)

                decrypted: str = decrypt_RSA(private_key, ciphertext).decode("utf-8")
                message._payload = HiveMessage.deserialize(decrypted)
            except:
                if k:
                    LOG.error("failed to decrypt message!")
                else:
                    LOG.debug("failed to decrypt message, not for us")
                return False

        if message.msg_type == HiveMessageType.BUS:
            self.handle_bus_message(message, client)
            return True
        elif message.msg_type == HiveMessageType.PROPAGATE:
            self.handle_propagate_message(message, client)
            return True
        elif message.msg_type == HiveMessageType.BROADCAST:
            self.handle_broadcast_message(message, client)
            return True
        elif message.msg_type == HiveMessageType.ESCALATE:
            self.handle_escalate_message(message, client)
            return True
        elif message.msg_type == HiveMessageType.BINARY:
            self.handle_binary_message(message, client)
            return True
        elif message.msg_type == HiveMessageType.SHARED_BUS:
            self.handle_client_shared_bus(message.payload, client)
            return True

        return False

    # HiveMind mycroft bus messages -  from slave -> master
    def _update_blacklist(self, message: Message, client: HiveMindClientConnection):
        LOG.debug("replacing message metadata with hivemind client session")
        message.context["session"] = client.sess.serialize()

        # update blacklist from db, to account for changes without requiring a restart
        self.db.sync()
        user = self.db.get_client_by_api_key(client.key)
        client.skill_blacklist = user.skill_blacklist or []
        client.intent_blacklist = user.intent_blacklist or []
        client.msg_blacklist = user.message_blacklist or []

        # inject client specific blacklist into session
        if "blacklisted_skills" not in message.context["session"]:
            message.context["session"]["blacklisted_skills"] = []
        if "blacklisted_intents" not in message.context["session"]:
            message.context["session"]["blacklisted_intents"] = []

        message.context["session"]["blacklisted_skills"] += [s for s in client.skill_blacklist
                                                             if
                                                             s not in message.context["session"]["blacklisted_skills"]]
        message.context["session"]["blacklisted_intents"] += [s for s in client.intent_blacklist
                                                              if s not in message.context["session"][
                                                                  "blacklisted_intents"]]
        return message

    def handle_inject_agent_msg(
            self, message: Message, client: HiveMindClientConnection
    ):
        """
        message (Message): mycroft bus message object
        """
        # A Slave wants to inject a message in internal mycroft bus
        # You are a Master, authorize bus message

        # messages/skills/intents per user
        if not client.authorize(message):
            LOG.warning(client.peer + " sent an unauthorized bus message")
            return

        # ensure client specific session data is injected in query to ovos
        message = self._update_blacklist(message, client)
        if message.msg_type == "speak":
            message.context["destination"] = ["audio"]  # make audible, this is injected "speak" command
        elif message.context.get("destination") is None:
            message.context["destination"] = "skills"  # ensure not treated as a broadcast

        # send client message to internal mycroft bus
        LOG.info(f"Forwarding message '{message.msg_type}' to agent bus from client: {client.peer}")
        message.context["peer"] = message.context["source"] = client.peer
        message.context["source"] = client.peer

        bus = self.get_bus(client)
        bus.emit(message)

        if self.agent_bus_callback:
            self.agent_bus_callback(message)

    def handle_client_shared_bus(self, message: Message, client: HiveMindClientConnection):
        # this message is going inside the client bus
        # take any metrics you need
        LOG.info("Monitoring bus from client: " + client.peer)
        if self.shared_bus_callback:
            self.shared_bus_callback(message)
