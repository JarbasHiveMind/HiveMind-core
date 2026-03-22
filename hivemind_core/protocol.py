# hivemind-core
# Copyright (C) 2026 Casimiro Ferreira
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
import dataclasses
import json
import os
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
from hivemind_core.hive_map import HiveMapper
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
                # For BUS messages: payload is OVOS Message
                # For PROPAGATE/ESCALATE/BROADCAST: payload is HiveMessage
                if hasattr(message.payload, 'serialize'):
                    LOG.debug(f"unencrypted payload size: {len(message.payload.serialize())} bytes")
                else:
                    LOG.debug(f"unencrypted payload size: {len(message.serialize())} bytes")
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
                if self.hm_protocol and self.hm_protocol.require_crypto:
                    # HELLO and HANDSHAKE are legitimately sent as plaintext
                    # during session establishment, before crypto is negotiated.
                    exempt = {HiveMessageType.HELLO, HiveMessageType.HANDSHAKE}
                    msg_type = ""
                    try:
                        parsed = json.loads(payload) if isinstance(payload, str) else {}
                        msg_type = parsed.get("msg_type", "")
                    except Exception:
                        pass
                    if msg_type not in exempt:
                        raise ValueError(
                            f"Encrypted message required but received plaintext from {self.peer}"
                        )
                LOG.warning("Message was unencrypted")
        else:
            pass  # TODO - reject anything except HELLO and HANDSHAKE

        if isinstance(payload, bytes):
            return decode_bitstring(payload)
        elif isinstance(payload, str):
            payload = json.loads(payload)
        return HiveMessage(**payload)

    def authorize(self, message: Message) -> bool:
        """parse the message being injected into ovos-core bus
        if this client is not authorized to inject it return False

        Empty allowed_types list means allow all messages (no restrictions).
        """
        # Empty whitelist = allow all (no restrictions configured)
        if self.allowed_types and message.msg_type not in self.allowed_types:
            return False

        # TODO check intent / skill that will trigger
        # for OVOS agent this is passed in Session and ignored during match
        # adding it here allows blocking the utterance completely instead
        # or adding a callback for specific agents to decide how to handle
        return True


@dataclass
class CascadeResponse:
    """A single response collected during a CASCADE query.

    Attributes:
        responder_peer: Peer ID of the node that produced this response.
        responder_site_id: Site ID of the responder (if available).
        messages: List of OVOS Messages in the response (e.g., multiple 'speak' messages).
        metadata: Full metadata from the response HiveMessage.
    """
    responder_peer: str
    responder_site_id: str = ""
    messages: List[Message] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class CascadeCollector:
    """Collects CASCADE responses for a given query_id.

    Attributes:
        query_id: The correlation ID for this CASCADE.
        originator_peer: Peer that originated the CASCADE.
        responses: All collected CascadeResponse objects.
    """
    query_id: str
    originator_peer: str
    responses: List[CascadeResponse] = field(default_factory=list)

    def add_response(self, message: HiveMessage) -> 'CascadeResponse':
        """Add a CASCADE response and return the CascadeResponse object.

        Args:
            message: The CASCADE response HiveMessage (is_response=True).

        Returns:
            The newly created CascadeResponse.
        """
        meta = message.metadata or {}
        resp = CascadeResponse(
            responder_peer=meta.get("responder_peer", "unknown"),
            responder_site_id=meta.get("responder_site_id", ""),
            metadata=meta,
        )
        # Extract OVOS Messages from the inner BUS payload
        inner = message.payload
        if isinstance(inner, HiveMessage) and inner.msg_type == HiveMessageType.BUS:
            bus_msg = inner.payload
            if isinstance(bus_msg, Message):
                resp.messages.append(bus_msg)
        self.responses.append(resp)
        return resp


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

    hive_mapper: HiveMapper = dataclasses.field(default_factory=HiveMapper)

    # Optional upstream connection: when set, this node is a relay.
    # Initialized via bind_upstream() with a HiveMindSlaveProtocol.
    _upstream_hm = None  # HiveMessageBusClient — sends HiveMessages to upstream master

    # below are optional callbacks to handle payloads
    # receives the payload + HiveMindClient that sent it
    escalate_callback = None  # slave asked to escalate payload
    illegal_callback = None  # slave asked to broadcast payload (illegal action)
    propagate_callback = None  # slave asked to propagate payload
    broadcast_callback = None  # slave asked to broadcast payload
    agent_bus_callback = None  # slave asked to inject payload into mycroft bus
    shared_bus_callback = None  # passive sharing of slave device bus (info)

    # CASCADE disambiguation: called when the originating node collects all
    # CASCADE responses for a given query_id.
    # Signature: cascade_select_callback(query_id: str, responses: List[CascadeResponse]) -> Optional[Message]
    # If set and returns a Message, that message is emitted on the local bus.
    # If None or not set, all responses are emitted individually.
    cascade_select_callback = None

    def __post_init__(self):
        self.clients = {}  # fix: was a class-level dict shared across all instances
        self._seen_flood_ids: set = set()
        self._pending_cascades: dict = {}  # query_id -> CascadeCollector
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
        except Exception:
            LOG.exception("error on connect callback")

        try:  # let the binary protocol know about it
            self.binary_data_protocol.callbacks.on_connect(client)
        except Exception:
            LOG.exception("error on connect binary callback")

        try:  # let the agent protocol know about it
            self.agent_protocol.callbacks.on_connect(client)
        except Exception:
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
            if user is None:
                LOG.warning(f"update_last_seen: client key not found in db: {client.key}")
                return
            user.last_seen = time.time()
            LOG.debug(f"updated last seen timestamp: {client.key} - {user.last_seen}")
            self.db.update_item(user)

    def handle_client_disconnected(self, client: HiveMindClientConnection):
        try:
            self.callbacks.on_disconnect(client)
        except Exception:
            LOG.exception("error on disconnect callback")

        try:  # let the binary protocol know about it
            self.binary_data_protocol.callbacks.on_disconnect(client)
        except Exception:
            LOG.exception("error on disconnect binary callback")

        try:  # let the agent protocol know about it
            self.agent_protocol.callbacks.on_disconnect(client)
        except Exception:
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
        except Exception:
            LOG.exception("error on invalid_key callback")

        try:  # let the binary protocol know about it
            self.binary_data_protocol.callbacks.on_invalid_key(client)
        except Exception:
            LOG.exception("error on invalid_key binary callback")

        try:  # let the agent protocol know about it
            self.agent_protocol.callbacks.on_invalid_key(client)
        except Exception:
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
        except Exception:
            LOG.exception("error on invalid_protocol callback")

        try:  # let the binary protocol know about it
            self.binary_data_protocol.callbacks.on_invalid_protocol(client)
        except Exception:
            LOG.exception("error on invalid_protocol binary callback")

        try:  # let the agent protocol know about it
            self.agent_protocol.callbacks.on_invalid_protocol(client)
        except Exception:
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
        elif message.msg_type == HiveMessageType.QUERY:
            self.handle_query_message(message, client)
        elif message.msg_type == HiveMessageType.CASCADE:
            self.handle_cascade_message(message, client)
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
        if message.msg_type != HiveMessageType.BINARY:
            LOG.warning(f"handle_binary_message called with wrong type: {message.msg_type}")
            return
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
            file_name = os.path.basename(message.metadata.get("file_name") or "")
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
            if not client.pswd_handshake.receive_and_verify(envelope):
                LOG.warning(f"Password mismatch from client: {client.peer}")
                self.handle_invalid_key_connected(client)
                client.disconnect()
                return

            # key is derived safely from password in both sides
            # the handshake validates both ends have the same password
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
        """
        Processes a HELLO message from a client to synchronize session data and register the client.
        
        Updates the client's session, site ID, and public key based on the message payload, and adds the client to the active clients registry.
        """
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
        LOG.debug(f"client session_id: {client.sess.session_id}")
        LOG.debug(f"client is_admin: {client.is_admin}")
        if client.sess.session_id == "default" and not client.is_admin:
            LOG.warning("Client requested 'default' session, but is not an administrator")
            client.disconnect()
        else:
            self.clients[client.peer] = client

    def handle_bus_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        # track any Session updates from client side
        """
        Handles internal bus messages from a client, enforcing session restrictions and forwarding to the agent bus.

        If a non-admin client attempts to use the "default" session ID, the client is disconnected. Otherwise, updates the client's session if the session ID matches and is not "default", then injects the message into the internal agent bus and invokes the agent bus callback if set.
        """
        sess = Session.from_message(message.payload)
        if sess.session_id == "default" and not client.is_admin:
            LOG.warning("Client tried to inject 'default' session message, action only allowed for administrators!")
            client.disconnect()
            return

        if sess.session_id != "default" and client.sess.session_id == sess.session_id:
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
            client.disconnect()
            return

        if self.broadcast_callback:
            self.broadcast_callback(payload)

        # Handle inner payload (does NOT short-circuit forwarding)
        if message.payload.msg_type == HiveMessageType.INTERCOM:
            self.handle_intercom_message(message.payload, client)
        elif message.payload.msg_type == HiveMessageType.BUS:
            site = message.target_site_id
            if site and site == self.identity.site_id:
                self.handle_bus_message(message.payload, client)

        # broadcast message to other peers, preserving the BROADCAST wrapper
        broadcast_fwd = HiveMessage(HiveMessageType.BROADCAST, payload=payload)
        for peer in self.clients:
            if peer == client.peer:
                continue
            self.clients[peer].send(broadcast_fwd)

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
            client.disconnect()
            return

        if self.propagate_callback:
            self.propagate_callback(payload)

        # Handle inner payload (does NOT short-circuit forwarding)
        if message.payload.msg_type == HiveMessageType.INTERCOM:
            self.handle_intercom_message(message.payload, client)
        elif message.payload.msg_type == HiveMessageType.BUS:
            site = message.target_site_id
            if site and site == self.identity.site_id:
                self.handle_bus_message(message.payload, client)

        if message.payload.msg_type == HiveMessageType.PING:
            self.handle_ping_message(payload, client)

        # propagate message to other peers, preserving the PROPAGATE wrapper
        propagate_fwd = HiveMessage(HiveMessageType.PROPAGATE, payload=payload)
        for peer in self.clients:
            if peer == client.peer:
                continue
            self.clients[peer].send(propagate_fwd)

        # forward upstream if this node is a relay
        self.propagate_to_master(payload)

    def handle_ping_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        """Handle an inner PING message received inside a PROPAGATE wrapper.

        Feeds the PING into the local ``HiveMapper``, emits ``hive.ping.received``
        on the agent bus, then — if this ``flood_id`` has not been seen before —
        builds and sends this node's own responsive PING (same ``flood_id``) to
        all peers and upstream.

        Args:
            message: Inner PING HiveMessage (route already transferred from outer
                PROPAGATE by ``_unpack_message``).
            client: Connection that delivered the PROPAGATE(PING).
        """
        ping_payload = message.payload
        if not isinstance(ping_payload, dict):
            LOG.warning("PING received with non-dict payload, ignoring")
            return

        flood_id = ping_payload.get("flood_id", "")

        # Always feed mapper (register sender info)
        self.hive_mapper.on_ping(message, received_at=time.time())

        # Emit bus event
        bus = self.get_bus(client)
        bus.emit(Message(
            "hive.ping.received",
            {
                "flood_id": flood_id,
                "peer": ping_payload.get("peer"),
                "site_id": ping_payload.get("site_id"),
                "route": message.route,
            },
            {"source": client.peer},
        ))

        # Flood-loop prevention: if we already responded to this flood_id, stop
        if not flood_id or flood_id in self._seen_flood_ids:
            return
        # Cap set size to prevent unbounded memory growth
        if len(self._seen_flood_ids) > 10000:
            self._seen_flood_ids.clear()
        self._seen_flood_ids.add(flood_id)

        # Relay masters skip own responsive PING — the satellite side
        # already responded upstream via HiveMindSlaveProtocol._handle_ping.
        if self._upstream_hm is not None:
            return

        # Build our own responsive PING with the same flood_id
        own_ping_payload = {
            "flood_id": flood_id,
            "peer": self.peer,
            "site_id": self.identity.site_id,
            "timestamp": time.time(),
        }
        own_ping_inner = HiveMessage(HiveMessageType.PING, own_ping_payload)
        own_ping_outer = HiveMessage(HiveMessageType.PROPAGATE, payload=own_ping_inner)

        LOG.debug(f"Sending responsive PING for flood_id={flood_id}")

        # Send to all downstream peers
        for peer_id, conn in self.clients.items():
            if peer_id == client.peer:
                continue
            conn.send(own_ping_outer)

        # Send back toward sender too (so they discover us)
        client.send(own_ping_outer)

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
            client.disconnect()
            return

        if self.escalate_callback:
            self.escalate_callback(payload)

        # Handle inner payload (does NOT short-circuit forwarding)
        if message.payload.msg_type == HiveMessageType.INTERCOM:
            self.handle_intercom_message(message.payload, client)
        elif message.payload.msg_type == HiveMessageType.BUS:
            site = message.target_site_id
            if site and site == self.identity.site_id:
                self.handle_bus_message(message.payload, client)

        # forward upstream if this node is a relay
        self.escalate_to_master(payload)

    def handle_query_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        """Handle a QUERY message: like ESCALATE but expects a response.

        Request (is_response=False): Inject BUS into local agent, check for
        synchronous response. If the agent handles it, send the response back
        downstream. If not, escalate upstream (or return error if top-level).

        Response (is_response=True): Route downstream toward the originator.

        Args:
            message: The QUERY HiveMessage.
            client: The client connection that sent the message.
        """
        LOG.info(f"Received QUERY from: {client.peer}")
        metadata = message.metadata or {}
        is_response = metadata.get("is_response", False)

        if is_response:
            # Route response downstream toward originator
            self._route_query_response(message, client)
            return

        # Request handling
        payload = self._unpack_message(message, client)

        if not client.can_escalate:
            LOG.warning("Received QUERY from client without escalate permission")
            if self.illegal_callback:
                self.illegal_callback(payload)
            client.disconnect()
            return

        query_id = metadata.get("query_id", str(uuid.uuid4()))
        originator_peer = metadata.get("originator_peer", client.peer)

        # Emit bus event
        bus = self.get_bus(client)
        bus.emit(Message(
            "hive.query.received",
            {"query_id": query_id, "originator_peer": originator_peer},
            {"source": client.peer},
        ))

        # Try to get a response from the local agent
        inner = message.payload
        if inner.msg_type == HiveMessageType.BUS:
            response = self._try_local_agent_query(inner.payload, client, query_id)
            if response is not None:
                # Agent answered — send response back to client
                resp_msg = self._build_query_response(
                    HiveMessageType.QUERY, response, query_id,
                    originator_peer, self.peer, route=message.route
                )
                client.send(resp_msg)
                return

        # Agent could not answer — escalate upstream or return error
        if self._upstream_hm is not None:
            self.query_to_master(payload, metadata)
        else:
            # Top-level master, no answer available
            LOG.info(f"QUERY {query_id}: no answer available (top-level master)")
            error_bus = Message(
                "hive.query.timeout",
                {"query_id": query_id, "error": "no_answer"},
            )
            error_resp = self._build_query_response(
                HiveMessageType.QUERY, error_bus, query_id,
                originator_peer, self.peer, route=message.route
            )
            client.send(error_resp)

    def handle_cascade_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        """Handle a CASCADE message: like PROPAGATE but expects responses from all nodes.

        Request (is_response=False): Inject BUS into local agent, forward to
        all other peers and upstream. Collect and relay responses.

        Response (is_response=True): Route downstream toward the originator.

        Args:
            message: The CASCADE HiveMessage.
            client: The client connection that sent the message.
        """
        LOG.info(f"Received CASCADE from: {client.peer}")
        metadata = message.metadata or {}
        is_response = metadata.get("is_response", False)

        if is_response:
            # Route response downstream toward originator
            self._route_query_response(message, client)
            return

        # Request handling
        payload = self._unpack_message(message, client)

        if not client.can_propagate:
            LOG.warning("Received CASCADE from client without propagate permission")
            if self.illegal_callback:
                self.illegal_callback(payload)
            client.disconnect()
            return

        query_id = metadata.get("query_id", str(uuid.uuid4()))
        originator_peer = metadata.get("originator_peer", client.peer)

        # Emit bus event
        bus = self.get_bus(client)
        bus.emit(Message(
            "hive.cascade.received",
            {"query_id": query_id, "originator_peer": originator_peer},
            {"source": client.peer},
        ))

        # Try local agent
        inner = message.payload
        if inner.msg_type == HiveMessageType.BUS:
            response = self._try_local_agent_query(inner.payload, client, query_id)
            if response is not None:
                resp_msg = self._build_query_response(
                    HiveMessageType.CASCADE, response, query_id,
                    originator_peer, self.peer, route=message.route
                )
                # Route through _route_query_response for disambiguation support
                self._route_query_response(resp_msg, client)

        # Forward CASCADE to all other downstream peers
        cascade_fwd = HiveMessage(HiveMessageType.CASCADE, payload=payload,
                                  metadata=metadata)
        for peer in self.clients:
            if peer == client.peer:
                continue
            self.clients[peer].send(cascade_fwd)

        # Forward upstream if relay
        self.cascade_to_master(payload, metadata)

    def _try_local_agent_query(
            self, bus_message: Message, client: HiveMindClientConnection,
            query_id: str
    ) -> Optional[Message]:
        """Inject a BUS message into the local agent and check for a synchronous response.

        Listens for a response on the agent bus that has a matching query_id
        in its context. Returns the response Message if found, None otherwise.

        Args:
            bus_message: The inner OVOS Message to inject.
            client: The client that originated the query.
            query_id: Correlation ID for matching the response.

        Returns:
            The response Message if the agent answered, None otherwise.
        """
        bus = self.get_bus(client)

        # Set up a one-shot listener for the response
        response_holder: List[Message] = []
        injected_type = bus_message.msg_type

        def _on_response(msg: Union[Message, str]):
            if isinstance(msg, str):
                try:
                    msg = Message.deserialize(msg)
                except Exception:
                    return
            # Skip the injected message itself (same msg_type as query)
            if msg.msg_type == injected_type:
                return
            if msg.context.get("query_id") == query_id:
                response_holder.append(msg)

        # Listen on the "message" catch-all to capture any response
        bus.on("message", _on_response)

        try:
            # Inject the message with query_id in context
            if not client.authorize(bus_message):
                LOG.warning(f"{client.peer} sent unauthorized QUERY bus message: '{bus_message.msg_type}'")
                return None

            bus_message = self._update_blacklist(bus_message, client)
            bus_message.context["peer"] = bus_message.context["source"] = client.peer
            bus_message.context["destination"] = "skills"
            bus_message.context["query_id"] = query_id
            bus.emit(bus_message)

            # Check if any synchronous response was captured
            if response_holder:
                return response_holder[0]
            return None
        finally:
            bus.remove("message", _on_response)

    def _build_query_response(
            self, msg_type: HiveMessageType, response: Message,
            query_id: str, originator_peer: str, responder_peer: str,
            route: Optional[list] = None
    ) -> HiveMessage:
        """Build a QUERY or CASCADE response HiveMessage.

        Args:
            msg_type: HiveMessageType.QUERY or HiveMessageType.CASCADE.
            response: The OVOS Message to wrap as response payload.
            query_id: Correlation ID from the original request.
            originator_peer: Peer that originated the query.
            responder_peer: Peer that is responding.
            route: Hop-by-hop route trail from the inbound request message.

        Returns:
            A HiveMessage with is_response=True in metadata.
        """
        inner = HiveMessage(HiveMessageType.BUS, payload=response)
        msg = HiveMessage(
            msg_type,
            payload=inner,
            metadata={
                "query_id": query_id,
                "originator_peer": originator_peer,
                "responder_peer": responder_peer,
                "is_response": True,
            },
        )
        if route:
            msg.replace_route(route)
        return msg

    def _route_query_response(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        """Route a QUERY/CASCADE response downstream toward the originator.

        For CASCADE responses, if cascade_select_callback is set and the
        originator is a direct client, the response is collected in a
        CascadeCollector. The callback is invoked each time a new response
        arrives, allowing progressive disambiguation.

        For QUERY responses, or CASCADE without a select callback, the
        response is forwarded immediately.

        Args:
            message: The response HiveMessage (is_response=True).
            client: The connection that delivered the response.
        """
        metadata = message.metadata or {}
        originator_peer = metadata.get("originator_peer", "")

        # CASCADE collection: if we have a select callback and the originator
        # is a direct client, collect responses for disambiguation
        if (message.msg_type == HiveMessageType.CASCADE
                and self.cascade_select_callback is not None
                and originator_peer in self.clients):
            query_id = metadata.get("query_id", "")
            if query_id not in self._pending_cascades:
                self._pending_cascades[query_id] = CascadeCollector(
                    query_id=query_id, originator_peer=originator_peer
                )
            collector = self._pending_cascades[query_id]
            collector.add_response(message)

            # Invoke the select callback (it decides when enough responses are in)
            bus = self.get_bus(self.clients[originator_peer])
            try:
                selected = self.cascade_select_callback(query_id, collector.responses)
                if selected is not None:
                    # Callback selected a winner — emit on bus and clean up
                    bus.emit(selected)
                    del self._pending_cascades[query_id]
            except Exception:
                LOG.exception(f"cascade_select_callback error for query_id={query_id}")
            return

        # Default routing: forward toward originator
        if originator_peer in self.clients:
            self.clients[originator_peer].send(message)
        else:
            # Forward to all downstream clients (except sender)
            for peer in self.clients:
                if peer == client.peer:
                    continue
                self.clients[peer].send(message)

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

                # SECURITY: RSA signature on INTERCOM messages is NOT verified.
                # To fix this, maintain a registry of trusted peer public keys
                # (e.g., loaded from a config or exchanged via an out-of-band channel)
                # and call: verified = verify_RSA(trusted_pub, ciphertext, signature)
                # Until then, any peer with knowledge of this node's public key can
                # send forged INTERCOM messages that will be silently accepted.

                private_key = load_RSA_key(self.identity.private_key)

                decrypted: str = decrypt_RSA(private_key, ciphertext).decode("utf-8")
                message._payload = HiveMessage.deserialize(decrypted)
            except Exception:
                if k:
                    LOG.error("failed to decrypt message!")
                else:
                    LOG.debug("failed to decrypt message, not for us")
                return False

        # Dispatch on the inner message type (not the outer INTERCOM type).
        # After decryption _payload is the inner HiveMessage; for unencrypted INTERCOM
        # it is the raw dict representation of the inner message.
        inner = message.payload
        if isinstance(inner, dict):
            try:
                inner = HiveMessage.deserialize(inner)
            except Exception:
                return False

        if inner.msg_type == HiveMessageType.BUS:
            self.handle_bus_message(inner, client)
            return True
        elif inner.msg_type == HiveMessageType.PROPAGATE:
            self.handle_propagate_message(inner, client)
            return True
        elif inner.msg_type == HiveMessageType.BROADCAST:
            self.handle_broadcast_message(inner, client)
            return True
        elif inner.msg_type == HiveMessageType.ESCALATE:
            self.handle_escalate_message(inner, client)
            return True
        elif inner.msg_type == HiveMessageType.BINARY:
            self.handle_binary_message(inner, client)
            return True
        elif inner.msg_type == HiveMessageType.SHARED_BUS:
            self.handle_client_shared_bus(inner.payload, client)
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
            LOG.warning(client.peer + f" sent an unauthorized bus message: '{message.msg_type}'")
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

    # --- Upstream connection (relay support) ---

    def bind_upstream(self, slave) -> None:
        """Bind a ``HiveMindSlaveProtocol`` as the upstream connection.

        After this call the node acts as a relay: transport messages from
        downstream satellites are forwarded upstream, and BROADCAST/PROPAGATE
        from the upstream master are forwarded to downstream clients.

        The slave protocol should share the same bus as this listener's
        agent protocol (``self.agent_protocol.bus``) so that both sides
        operate on a common event bus.

        Args:
            slave: A ``HiveMindSlaveProtocol`` instance, already bound
                   (``slave.bind(bus)`` called).
        """
        self._upstream_hm = slave.hm

        # When the upstream master sends BROADCAST or PROPAGATE down to us,
        # forward to all our downstream clients.
        slave.hm.on(HiveMessageType.BROADCAST, self.broadcast_from_master)
        slave.hm.on(HiveMessageType.PROPAGATE, self.propagate_from_master)
        slave.hm.on(HiveMessageType.QUERY, self.query_from_master)
        slave.hm.on(HiveMessageType.CASCADE, self.cascade_from_master)

    def escalate_to_master(self, payload: HiveMessage) -> None:
        """Forward an ESCALATE message to the upstream master.

        Wraps the inner payload in ``HiveMessage(ESCALATE, ...)`` and sends
        via the upstream ``HiveMessageBusClient``.  If no upstream is bound,
        the call is a no-op (this node is the top-level master).

        Args:
            payload: The inner HiveMessage to escalate upstream.
        """
        if self._upstream_hm is None:
            return
        self._upstream_hm.emit(HiveMessage(HiveMessageType.ESCALATE, payload=payload))

    def propagate_to_master(self, payload: HiveMessage) -> None:
        """Forward a PROPAGATE message to the upstream master.

        Wraps the inner payload in ``HiveMessage(PROPAGATE, ...)`` and sends
        via the upstream ``HiveMessageBusClient``.  If no upstream is bound,
        the call is a no-op (this node is the top-level master).

        Args:
            payload: The inner HiveMessage to propagate upstream.
        """
        if self._upstream_hm is None:
            return
        self._upstream_hm.emit(HiveMessage(HiveMessageType.PROPAGATE, payload=payload))

    def query_to_master(self, payload: HiveMessage, metadata: Optional[dict] = None) -> None:
        """Forward a QUERY message to the upstream master.

        Args:
            payload: The inner HiveMessage to send upstream.
            metadata: Query metadata (query_id, originator_peer, etc.).
        """
        if self._upstream_hm is None:
            return
        self._upstream_hm.emit(HiveMessage(HiveMessageType.QUERY, payload=payload,
                                           metadata=metadata))

    def cascade_to_master(self, payload: HiveMessage, metadata: Optional[dict] = None) -> None:
        """Forward a CASCADE message to the upstream master.

        Args:
            payload: The inner HiveMessage to send upstream.
            metadata: Query metadata (query_id, originator_peer, etc.).
        """
        if self._upstream_hm is None:
            return
        self._upstream_hm.emit(HiveMessage(HiveMessageType.CASCADE, payload=payload,
                                           metadata=metadata))

    def query_from_master(self, message: HiveMessage) -> None:
        """Forward a QUERY received from the upstream master to all downstream clients.

        Args:
            message: The QUERY HiveMessage received from upstream.
        """
        for peer, conn in self.clients.items():
            conn.send(message)

    def cascade_from_master(self, message: HiveMessage) -> None:
        """Forward a CASCADE received from the upstream master to all downstream clients.

        Args:
            message: The CASCADE HiveMessage received from upstream.
        """
        for peer, conn in self.clients.items():
            conn.send(message)

    def broadcast_from_master(self, message: HiveMessage) -> None:
        """Forward a BROADCAST received from the upstream master to all downstream clients.

        Args:
            message: The BROADCAST HiveMessage received from upstream.
        """
        for peer, conn in self.clients.items():
            conn.send(message)

    def propagate_from_master(self, message: HiveMessage) -> None:
        """Forward a PROPAGATE received from the upstream master to all downstream clients.

        Args:
            message: The PROPAGATE HiveMessage received from upstream.
        """
        for peer, conn in self.clients.items():
            conn.send(message)
