# hivemind-core
# Copyright (C) 2026 Casimiro Ferreira
# SPDX-License-Identifier: Apache-2.0
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
try:
    from hivemind_bus_client.noise import (NOISE_SUPPORTED, NOISE_PATTERNS, NOISE_SUITES,
                                           NOISE_PATTERN_KK, NoiseTransport,
                                           NoiseHandshakeFailed, NoiseTransportFailed,
                                           build_prologue, noise_protocol_name,
                                           start_noise_handshake)
except ImportError:
    # hivemind_bus_client without the protocol v3 noise module: the server
    # degrades gracefully to the legacy (v2 and below) handshake and never
    # advertises protocol v3. The stubs below are only referenced on code
    # paths gated behind NOISE_SUPPORTED / an established v3 session.
    NOISE_SUPPORTED = False
    NOISE_PATTERNS, NOISE_SUITES = [], []
    NOISE_PATTERN_KK = "KKpsk0"

    class NoiseHandshakeFailed(Exception):
        """Stub: protocol v3 unavailable."""

    class NoiseTransportFailed(Exception):
        """Stub: protocol v3 unavailable."""

    class NoiseTransport:  # pragma: no cover - never instantiated without noise
        def __init__(self, *args, **kwargs):
            raise NoiseHandshakeFailed("protocol v3 (Noise) support unavailable: "
                                       "hivemind_bus_client.noise not importable")

    def build_prologue(*args, **kwargs):  # pragma: no cover
        raise NoiseHandshakeFailed("protocol v3 (Noise) support unavailable")

    def noise_protocol_name(*args, **kwargs):  # pragma: no cover
        raise NoiseHandshakeFailed("protocol v3 (Noise) support unavailable")

    def start_noise_handshake(*args, **kwargs):  # pragma: no cover
        raise NoiseHandshakeFailed("protocol v3 (Noise) support unavailable")
from hivemind_core.database import ClientDatabase
from hivemind_bus_client.hive_map import HiveMapper
from hivemind_plugin_manager.protocols import AgentProtocol, BinaryDataHandlerProtocol, ClientCallbacks
from hivemind_plugin_manager.database import Client
from hivemind_plugin_manager.policy import PolicyPlugin
from hivemind_core.policy import PolicyChain
from poorman_handshake import HandShake, PasswordHandShake
from poorman_handshake.asymmetric.utils import decrypt_RSA, load_RSA_key, verify_RSA


class ProtocolVersion(IntEnum):
    ZERO = 0  # json only, no handshake, no binary
    ONE = 1  # handshake https://github.com/JarbasHiveMind/HiveMind-core/pull/29
    TWO = 2  # binary https://github.com/JarbasHiveMind/hivemind_websocket_client/pull/4
    THREE = 3  # Noise handshake, always-encrypted session (HIVEMIND-CRYPTO-1 §3.4)


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


# QUERY/CASCADE answers stream as a sequence of response chunks terminated by a
# response wrapping this control message — the end-of-stream is part of the
# protocol content, not loose metadata.
QUERY_STREAM_END = "hive.query.complete"


def _non_negative_float(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


class UnencryptedMessageError(ValueError):
    """Raised when a cleartext frame arrives on a connection that requires crypto.

    Only HELLO and HANDSHAKE messages may travel unencrypted (they precede
    session-key establishment); any other cleartext frame on a
    ``crypto_required`` server is rejected and the client disconnected
    (HIVEMIND-CRYPTO-1 §4).
    """


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

    # admission whitelist — list of ovos message_type values this client
    # may inject onto the agent bus. Enforced by MessageTypeACLPolicy
    # (hivemind_core.policy.MessageTypeACLPolicy). Empty = deny everything.
    # This is the only ACL field on the connection. There is no message
    # blacklist by design: hivemind-core is whitelist-only, deny-by-default.
    allowed_types: List[str] = field(default_factory=list)
    binarize: bool = False
    site_id: str = "unknown"
    can_escalate: bool = True
    can_propagate: bool = True
    is_admin: bool = False
    last_seen: float = -1

    hm_protocol: Optional['HiveMindListenerProtocol'] = None

    cipher: Literal[SupportedCiphers] = SupportedCiphers.AES_GCM
    encoding: Literal[SupportedEncodings] = SupportedEncodings.JSON_HEX

    # protocol v3 (Noise handshake) state — HIVEMIND-CRYPTO-1 §3.4. On a v3
    # connection ``noise_transport`` replaces ``crypto_key`` as the session
    # layer; both stay None on v2-and-below connections (legacy path untouched)
    noise_handshake: Optional[object] = field(default=None, repr=False)
    noise_transport: Optional[NoiseTransport] = field(default=None, repr=False)
    # exact payloads of the cleartext HELLO + parameter HANDSHAKE sent to this
    # client, retained for Noise prologue binding (CRYPTO-1 §3.4.3)
    _hello_payload: Optional[dict] = field(default=None, init=False, repr=False)
    _handshake_payload: Optional[dict] = field(default=None, init=False, repr=False)

    # Connection-scoped resolved-user cache. Policies call ``resolve_user``
    # which hits the DB at most once per ``ttl`` window; ``invalidate_user``
    # forces the next call to refetch. Avoids per-policy DB sync() storms
    # on the admission hot path. Not part of the public field set.
    _resolved_user: Optional[Client] = field(default=None, init=False, repr=False)
    _resolved_user_ts: float = field(default=0.0, init=False, repr=False)

    def resolve_user(self, db, ttl: float = 5.0,
                     force: bool = False) -> Optional[Client]:
        """Return the cached DB row for this connection, refetching at
        most every ``ttl`` seconds (or unconditionally when ``force``).

        Looks up by ``client_id`` (via ``db.refresh``) when available,
        falling back to the api-key path otherwise. Exceptions from the
        DB propagate — callers fail-closed.
        """
        if (not force
                and self._resolved_user is not None
                and time.time() - self._resolved_user_ts <= ttl):
            return self._resolved_user
        client_id = getattr(self._resolved_user, "client_id", None)
        if client_id is not None:
            user = db.refresh(client_id)
        else:
            user = db.get_client_by_api_key(self.key)
        self._resolved_user = user
        self._resolved_user_ts = time.time()
        return self._resolved_user

    def invalidate_user(self) -> None:
        """Drop the cached resolved user so the next ``resolve_user`` call
        forces a fresh DB lookup."""
        self._resolved_user = None
        self._resolved_user_ts = 0.0

    def __post_init__(self):
        self.handshake = self.handshake or HandShake(self.hm_protocol.identity.private_key)

    @property
    def peer(self) -> str:
        # friendly id that ovos components can use to refer to this connection
        # this is how ovos refers to connected nodes in message.context
        return f"{self.name}::{self.sess.session_id}"

    def send(self, message: HiveMessage):
        is_bin = message.msg_type == HiveMessageType.BINARY
        if not is_bin and message.msg_type == HiveMessageType.BUS:
            _payload_type = (message.payload.get("type")
                             if isinstance(message.payload, dict)
                             else message.payload.msg_type)
            LOG.debug(f"mycroft_type {_payload_type}")

        LOG.debug(f"sending to {self.peer}: {message.msg_type}")

        if self.noise_transport is not None:
            # protocol v3: every message (HELLO/HANDSHAKE included) is a Noise
            # transport message — there is no cleartext v3 session (§3.4.5)
            if self.binarize or is_bin:
                payload = get_bitstring(hive_type=message.msg_type,
                                        payload=message.payload,
                                        hivemeta=message.metadata,
                                        binary_type=message.bin_type).bytes
            else:
                payload = message.serialize()
            self.send_msg(self.noise_transport.encrypt_frame(payload), True)
            return

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
                plaintext = message.serialize()
                LOG.debug(f"unencrypted payload size: {len(plaintext)} bytes")
                payload = encrypt_as_json(
                    key=self.crypto_key, plaintext=plaintext,
                    cipher=self.cipher, encoding=self.encoding
                )  # json string
            LOG.debug(f"encrypted payload size: {len(payload)} bytes")
        else:
            payload = message.serialize()
            LOG.debug(f"sent unencrypted!")

        self.send_msg(payload, is_bin)

    @property
    def crypto_required(self) -> bool:
        """True when the listener this connection belongs to mandates encryption.

        Mirrors the ``crypto_required`` flag advertised to clients in the
        HANDSHAKE payload (``HiveMindListenerProtocol.require_crypto``).
        """
        return bool(self.hm_protocol and self.hm_protocol.require_crypto)

    def decode(self, payload: str) -> HiveMessage:
        encrypted = False
        if self.noise_transport is not None:
            # protocol v3 session: only valid Noise transport messages are
            # accepted; tampering/replay/reordering fails AEAD and is fatal
            if not isinstance(payload, bytes):
                self.disconnect()
                raise NoiseTransportFailed(
                    "non-Noise message received on a protocol v3 session")
            try:
                payload = self.noise_transport.decrypt_frame(payload)
            except NoiseTransportFailed:
                LOG.error(f"rejecting invalid Noise transport message from "
                          f"{self.peer} (tampered, replayed or out-of-order), "
                          "disconnecting")
                self.disconnect()
                raise
            # a decoded Noise transport frame is authenticated + encrypted
            encrypted = True
        elif self.crypto_key:
            # handle binary encryption
            if isinstance(payload, bytes):
                payload = decrypt_bin(key=self.crypto_key, ciphertext=payload,
                                      cipher=self.cipher)
                encrypted = True
            # handle json encryption
            elif "ciphertext" in payload:
                payload = decrypt_from_json(key=self.crypto_key, ciphertext_json=payload,
                                            encoding=self.encoding, cipher=self.cipher)
                encrypted = True
            else:
                LOG.warning("Message was unencrypted")

        if isinstance(payload, bytes):
            message = decode_bitstring(payload)
        else:
            if isinstance(payload, str):
                payload = json.loads(payload)
            message = HiveMessage(**payload)

        # HIVEMIND-CRYPTO-1 §4 - when the server requires crypto, drop any
        # cleartext frame that is not part of key establishment. HELLO and
        # HANDSHAKE MUST remain accepted in the clear (they precede the
        # session key); everything else is rejected and the client dropped.
        if (not encrypted
                and self.crypto_required
                and message.msg_type not in (HiveMessageType.HELLO,
                                             HiveMessageType.HANDSHAKE)):
            LOG.error(f"Dropping unencrypted {message.msg_type} message from "
                      f"{self.peer}: server requires crypto")
            self.disconnect()
            raise UnencryptedMessageError(
                f"unencrypted {message.msg_type} message rejected: "
                f"crypto is required")
        return message

    def authorize(self, message: Message) -> bool:
        """Subclass override hook — return False to short-circuit bus
        injection without going through the policy chain.

        The allowed_types whitelist that used to live here moved to
        MessageTypeACLPolicy in hivemind_core/policy.py (see #85). Kept as a
        default-True stub so subclasses overriding it for ad-hoc
        admission gates continue to work.
        """
        # legacy hooks: subclasses may still want to plug intent / skill
        # decisions here outside the policy chain
        # for OVOS agent this is passed in Session and ignored during match
        # adding it here allows blocking the utterance completely instead
        # or adding a callback for specific agents to decide how to handle
        return True


@dataclass
class CascadeResponse:
    """A single response collected during a CASCADE query."""
    responder_peer: str
    responder_site_id: str = ""
    messages: List[Message] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class CascadeCollector:
    """Collects CASCADE responses for a given query_id at the originator."""
    query_id: str
    originator_peer: str
    responses: List[CascadeResponse] = field(default_factory=list)

    def add_response(self, message: HiveMessage) -> 'CascadeResponse':
        meta = message.metadata or {}
        resp = CascadeResponse(
            responder_peer=meta.get("responder_peer", "unknown"),
            responder_site_id=meta.get("responder_site_id", ""),
            metadata=meta,
        )
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
    policy_chain: Optional[PolicyChain] = None

    # below are optional callbacks to handle payloads
    # receives the payload + HiveMindClient that sent it
    escalate_callback = None  # slave asked to escalate payload
    illegal_callback = None  # slave asked to broadcast payload (illegal action)
    propagate_callback = None  # slave asked to propagate payload
    broadcast_callback = None  # slave asked to broadcast payload
    agent_bus_callback = None  # slave asked to inject payload into mycroft bus
    shared_bus_callback = None  # passive sharing of slave device bus (info)
    _upstream_hm = None  # HiveMessageBusClient to the upstream master when this node relays
    cascade_select_callback = None  # (query_id, [CascadeResponse]) -> Optional[Message]; CASCADE disambiguation
    query_timeout = 8.0  # seconds to wait for the local agent to answer a QUERY/CASCADE
    default_lang = "en-US"

    def __post_init__(self):
        self.clients = {}
        # TOFU pinning store for INTERCOM origin authentication
        # (HIVEMIND-CRYPTO-1 §5). Maps a client's access key to the PEM
        # public key it presented; once pinned, INTERCOM signatures from that
        # client MUST verify against the pinned key. In-memory for now — pins
        # last for the lifetime of this listener (the Client DB model has no
        # pubkey column yet).
        self.trusted_pubkeys: dict = {}  # client.key -> PEM public key
        self._seen_flood_ids: set = set()
        self._pending_cascades: dict = {}  # query_id -> CascadeCollector
        self._last_seen_updates: dict = {}  # client.key -> last persisted timestamp
        self.last_seen_update_interval = _non_negative_float(
            get_server_config().get("last_seen_update_interval", 0),
            0.0,
        )
        self.agent_protocol.hm_protocol = self
        if not self.binary_data_protocol:
            # just logs received messages
            self.binary_data_protocol = BinaryDataHandlerProtocol(hm_protocol=self,
                                                                  agent_protocol=self.agent_protocol)
        else:
            self.binary_data_protocol.hm_protocol = self
        if self.policy_chain is None:
            from hivemind_core.policy import MessageTypeACLPolicy, DenyAllPolicy
            cfg = get_server_config()
            try:
                chain = PolicyChain.from_config(cfg, hm_protocol=self)
            except Exception:
                LOG.exception(
                    "failed to build policy chain; installing DenyAllPolicy "
                    "fallback — every admission will be rejected until "
                    "configuration is fixed"
                )
                self.policy_chain = PolicyChain(
                    policies=[DenyAllPolicy(hm_protocol=self)],
                )
            else:
                # MessageTypeACLPolicy is the canonical allowed_types whitelist
                # enforcement and is non-removable. Prepend it to the
                # configured chain (deduping if an operator listed it
                # explicitly). Always mandatory — _optional[0] = False.
                configured: List[PolicyPlugin] = []
                configured_optional: List[bool] = []
                for i, p in enumerate(chain.policies):
                    if isinstance(p, MessageTypeACLPolicy):
                        continue
                    configured.append(p)
                    configured_optional.append(
                        chain._optional[i] if i < len(chain._optional) else False
                    )
                self.policy_chain = PolicyChain(
                    policies=[MessageTypeACLPolicy(hm_protocol=self), *configured],
                    _optional=[False, *configured_optional],
                )

    def get_bus(self, client: HiveMindClientConnection) -> Union[FakeBus, MessageBusClient]:
        # The agent decides which bus a client's messages land on. Default
        # agents return their single shared bus; a multiplexing agent (one
        # isolated brain per access key) returns a per-client bus, so per-key
        # routing on the inject path stays transparent here.
        return self.agent_protocol.get_bus(client)

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

        crypto_min = (
            ProtocolVersion.ONE
            if client.crypto_key is None and self.require_crypto
            else ProtocolVersion.ZERO
        )
        # deployment-configured protocol floor (HIVEMIND-WIRE-1 §2); default 2
        # refuses the oldest json-only / no-binary clients. The advertised
        # minimum is the stricter of the configured floor and the crypto-derived
        # minimum.
        try:
            cfg_min = ProtocolVersion(int(get_server_config().get("min_protocol_version", 2)))
        except (ValueError, KeyError):
            cfg_min = ProtocolVersion.TWO
        min_version = ProtocolVersion(max(int(cfg_min), int(crypto_min)))

        # protocol v3 (Noise handshake) needs the noise primitive and a shared
        # password for the PSK; binary framing (v2) needs binarization enabled;
        # otherwise the connection tops out at the legacy handshake (v1).
        v3_capable = NOISE_SUPPORTED and client.pswd_handshake is not None
        if v3_capable:
            max_version = ProtocolVersion.THREE
        elif get_server_config().get("binarize", False):
            max_version = ProtocolVersion.TWO
        else:
            max_version = ProtocolVersion.ONE

        if min_version > max_version:
            LOG.warning(
                f"rejecting {client.peer}: server requires protocol version "
                f">= {int(min_version)} but this connection can offer at most "
                f"{int(max_version)}"
            )
            client.disconnect()
            return

        hello_payload = {
            "pubkey": client.handshake.pubkey,
            # allows any node to verify messages are signed with this
            "peer": client.peer,  # this identifies the connected client in ovos message.context
            "node_id": self.peer
        }
        client._hello_payload = hello_payload  # bound into the Noise prologue
        msg = HiveMessage(HiveMessageType.HELLO, payload=hello_payload)
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
        if v3_capable:
            # advertise supported Noise patterns/suites, preference ordered
            # (CRYPTO-1 §3.4.1/§3.4.2). KKpsk0 only when this client's static
            # key was pinned by a previous XXpsk2 handshake.
            patterns = list(NOISE_PATTERNS)
            if not self._get_pinned_client_noise_key(client):
                patterns = [p for p in patterns if p != NOISE_PATTERN_KK]
            payload["noise"] = {"patterns": patterns, "suites": list(NOISE_SUITES)}
        client._handshake_payload = payload  # bound into the Noise prologue
        msg = HiveMessage(HiveMessageType.HANDSHAKE, payload)
        LOG.debug(f"starting {client.peer} HANDSHAKE: {payload}")
        client.send(msg)
        # if client is in protocol V1 -> self.handle_handshake_message
        # clients can rotate their pubkey or session_key by sending a new handshake

    def update_last_seen(self, client: HiveMindClientConnection):
        """track timestamps of last client interaction"""
        update_interval = getattr(self, "last_seen_update_interval", 0)
        mono_now = None
        if update_interval > 0:
            mono_now = time.monotonic()
            last_update = self._last_seen_updates.get(client.key)
            if last_update is not None and mono_now - last_update < update_interval:
                return
        with self.db:
            user = self.db.get_client_by_api_key(client.key)
            if user is None:
                # key was revoked / never existed — nothing to update
                LOG.debug(f"can not update last seen, no client for key: {client.key}")
                self._last_seen_updates.pop(client.key, None)
                return
            user.last_seen = time.time()
            LOG.debug(f"updated last seen timestamp: {client.key} - {user.last_seen}")
            self.db.update_item(user)
            if mono_now is not None:
                self._last_seen_updates[client.key] = mono_now

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
        if not any(conn.key == client.key for conn in self.clients.values()):
            self._last_seen_updates.pop(client.key, None)
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
        assert message.msg_type == HiveMessageType.BINARY
        bin_data = message.payload

        # policy admission chain — issue #85
        verdict = self.policy_chain.review_binary(bin_data, client)
        if verdict.denied:
            LOG.info(f"policy denied binary payload from {client.peer}: "
                     f"{verdict.code} ({verdict.reason})")
            denied = Message(
                "hive.policy.denied",
                {
                    "denied_type": "binary",
                    "bin_type": str(getattr(message, "bin_type", "")),
                    "code": verdict.code,
                    "reason": verdict.reason,
                    "data": verdict.data,
                },
                {"source": "hivemind-core", "destination": client.peer},
            )
            try:
                client.send(HiveMessage(HiveMessageType.BUS, payload=denied))
            except Exception:
                LOG.exception("failed to send hive.policy.denied for binary")
            return

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
            # SECURITY: file_name is client-supplied. Strip any directory
            # components so a malicious peer can not escape the intended
            # download directory (eg. "../../etc/passwd" -> "passwd").
            safe_name = os.path.basename(file_name) if file_name else ""
            if not safe_name or safe_name in (".", ".."):
                LOG.warning(f"Rejecting binary FILE with unsafe file_name: {file_name!r}")
                return
            self.binary_data_protocol.handle_receive_file(bin_data, safe_name, client)
        elif message.bin_type == HiveMindBinaryPayloadType.NUMPY_IMAGE:
            # TODO - convert to numpy array
            camera_id = message.metadata.get("camera_id")
            self.binary_data_protocol.handle_numpy_image(bin_data, camera_id, client)
        else:
            LOG.warning(f"Ignoring received untyped binary data: {len(bin_data)} bytes")

    # ------------------------------------------------- protocol v3 (Noise)
    def _get_pinned_client_noise_key(self, client: HiveMindClientConnection) -> Optional[str]:
        """Pinned Noise static public key for this client identity, if any.

        Pins live in the client database row's metadata (TOFU-then-pin,
        CRYPTO-1 §3.4.5). Failures are treated as 'not pinned'.
        """
        try:
            with self.db:
                user = self.db.get_client_by_api_key(client.key)
            if user is not None:
                return (user.metadata or {}).get("noise_pubkey")
        except Exception:
            LOG.exception("failed to look up pinned noise key")
        return None

    def _pin_client_noise_key(self, client: HiveMindClientConnection, pubkey: str) -> None:
        """Persist a client's Noise static public key against its identity."""
        try:
            with self.db:
                user = self.db.get_client_by_api_key(client.key)
                if user is None:
                    return
                user.metadata = user.metadata or {}
                user.metadata["noise_pubkey"] = pubkey
                self.db.update_item(user)
        except Exception:
            LOG.exception("failed to pin client noise key")

    def _abort_noise_handshake(self, client: HiveMindClientConnection, reason: str):
        """Fatal Noise handshake failure — reject the connection (§3.4.3)."""
        LOG.error(f"protocol v3 handshake with {client.peer} FAILED: {reason}")
        client.noise_handshake = None
        client.noise_transport = None
        self.handle_invalid_key_connected(client)
        client.disconnect()

    def handle_noise_handshake_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        """Server side of the protocol v3 Noise handshake (CRYPTO-1 §3.4.3).

        The node is the Noise initiator; this server is the responder. Noise
        message 1 names the selected pattern/suite and starts the handshake;
        for XXpsk2 a final message 3 authenticates the node's static key.
        A wrong password (PSK), tampered negotiation (prologue mismatch) or
        pinned-key contradiction aborts cryptographically, fail-fast.
        """
        noise_params = message.payload.get("noise") or {}
        try:
            noise_msg = bytes.fromhex(noise_params["msg"])
        except (KeyError, TypeError, ValueError):
            self._abort_noise_handshake(client, "malformed Noise envelope")
            return

        if client.noise_handshake is None:
            # Noise message 1: fixes the Noise protocol name
            offered = (client._handshake_payload or {}).get("noise") or {}
            pattern = noise_params.get("pattern")
            suite = noise_params.get("suite")
            if pattern not in (offered.get("patterns") or []) or \
                    suite not in (offered.get("suites") or []):
                self._abort_noise_handshake(
                    client, f"pattern/suite not offered: {pattern}/{suite}")
                return
            pinned = self._get_pinned_client_noise_key(client)
            if pattern == NOISE_PATTERN_KK and not pinned:
                self._abort_noise_handshake(client, "KKpsk0 without a pinned key")
                return
            name = noise_protocol_name(pattern, suite)
            prologue = build_prologue(client._hello_payload or {},
                                      client._handshake_payload or {}, name)
            try:
                client.noise_handshake = start_noise_handshake(
                    initiator=False, pattern=pattern, suite=suite,
                    password=client.pswd_handshake.password,
                    node_id=self.peer, prologue=prologue,
                    key_path=self.identity.noise_key,
                    remote_pubkey=pinned if pattern == NOISE_PATTERN_KK else None)
                node_payload = json.loads(
                    client.noise_handshake.read_message(noise_msg) or b"{}")
                # honour the node's binarize capability; encodings are framing
                # negotiation only — a v3 session is encrypted by the Noise
                # CipherStates regardless of encoding (WIRE-1 §3)
                client.binarize = bool(node_payload.get("binarize", False))
                encodings = [_norm_encoding(e) for e in
                             node_payload.get("encodings") or []] or [SupportedEncodings.JSON_HEX]
                client.encoding = encodings[0]
                msg2 = client.noise_handshake.write_message(
                    json.dumps({"encoding": client.encoding}).encode("utf-8"))
            except Exception as e:
                self._abort_noise_handshake(client, f"handshake failure: {e}")
                return
            client.send(HiveMessage(HiveMessageType.HANDSHAKE,
                                    {"noise": {"msg": msg2.hex()}}))
            if not client.noise_handshake.handshake_finished:
                return  # XXpsk2: wait for Noise message 3
        else:
            # XXpsk2 message 3: node's (encrypted) static key + final DH mix
            try:
                client.noise_handshake.read_message(noise_msg)
            except Exception as e:
                self._abort_noise_handshake(client, f"handshake failure: {e}")
                return

        # handshake complete -> Split(); transport CipherStates take over
        try:
            transport = NoiseTransport(client.noise_handshake)
        except NoiseHandshakeFailed as e:
            self._abort_noise_handshake(client, str(e))
            return

        # TOFU-then-pin the node's static key (§3.4.5)
        pinned = self._get_pinned_client_noise_key(client)
        if pinned and transport.remote_static_key != pinned:
            self._abort_noise_handshake(
                client, "client Noise static key contradicts pinned key")
            return
        if not pinned and transport.remote_static_key:
            self._pin_client_noise_key(client, transport.remote_static_key)

        client.noise_transport = transport
        client.noise_handshake = None
        client.crypto_key = None  # v3 replaces the v2 session AEAD entirely
        LOG.info(f"protocol v3 Noise session established with {client.peer}")

    def handle_handshake_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        if "noise" in message.payload:
            # protocol v3 negotiated (HIVEMIND-WIRE-1 §2)
            if not NOISE_SUPPORTED or client.pswd_handshake is None or \
                    not (client._handshake_payload or {}).get("noise"):
                self._abort_noise_handshake(client, "protocol v3 not offered")
                return
            self.handle_noise_handshake_message(message, client)
            return

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
            # fail-fast: verify the client's envelope was built with the same
            # password before deriving a key (HIVEMIND-CRYPTO-1 §3.2
            # RECOMMENDED explicit reject). A wrong password previously only
            # surfaced as a decrypt failure on the first encrypted frame.
            try:
                verified = client.pswd_handshake.receive_and_verify(envelope)
            except Exception:
                verified = False
            if not verified:
                LOG.warning("Client password handshake verification failed")
                self.handle_invalid_key_connected(client)
                client.disconnect()
                return

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
            # TOFU pin: first pubkey seen for this access key becomes the
            # trust anchor for INTERCOM signature verification. A later HELLO
            # presenting a different key does NOT overwrite the pin.
            pinned = self.trusted_pubkeys.get(client.key)
            if pinned is None:
                self.trusted_pubkeys[client.key] = client.pub_key
                LOG.debug(f"pinned public key for {client.peer}")
            elif pinned != client.pub_key:
                LOG.warning(f"client {client.peer} presented a public key that "
                            f"does not match its pinned key; keeping the pin")
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
        try:
            payload = message.payload
        except (AttributeError, KeyError, TypeError, ValueError):
            LOG.warning("Ignoring BUS payload with invalid message/context shape")
            return

        if not isinstance(payload, Message) or not isinstance(payload.context, dict):
            LOG.warning("Ignoring BUS payload with invalid message/context shape")
            return

        raw_session = payload.context.get("session") or {}
        sent_pipeline = isinstance(raw_session, dict) and "pipeline" in raw_session
        sess = Session.from_message(payload)
        if sent_pipeline:
            sess.pipeline = raw_session.get("pipeline")
        # The per-message "session_id == 'default'" gate moved to
        # OVOSAgentPolicy.review (HiveMind-core#85). Non-admin clients
        # injecting a default-session payload get Verdict.deny(
        # "session_id_default_forbidden", ...) and the message is dropped
        # with a hive.policy.denied response — replacing the previous
        # severe `client.disconnect()` reaction. The HELLO-time check at
        # handle_hello_message stays as connection-establishment gate.

        if sess.session_id != "default" and client.sess.session_id == sess.session_id:
            if not sent_pipeline:
                sess.pipeline = client.sess.pipeline
            client.sess = sess
            LOG.debug(f"Client session updated from payload: {sess.serialize()}")

        self.handle_inject_agent_msg(payload, client)

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
            # kick client for misbehaviour so it stops doing that
            client.disconnect()
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

    @property
    def _node_id(self) -> str:
        """Stable, unique per-node identity used for HIVEMIND-MSG-1 §5 loop
        detection.

        This is the node's cryptographic public key
        (:attr:`NodeIdentity.public_key`). It is the only identity that is
        both **unique per node** and **stable across connections/sessions**,
        and it is already how the mesh addresses individual nodes end-to-end
        (INTERCOM ``target_public_key``; see :meth:`handle_intercom_message`).

        It is deliberately **not** ``self.peer``: that field is a class default
        ``"master:0.0.0.0"`` that ``service.py`` never overrides, so every
        deployed node would share it — keying loop detection off it makes every
        node treat every other node's hop as "me" and false-drops legitimate
        multi-hop traffic at the second relay. It is also **not** ``site_id``:
        several nodes may share one site.
        """
        return self.identity.public_key

    def _is_routing_loop(self, message: HiveMessage) -> bool:
        """HIVEMIND-MSG-1 §5 loop suppression.

        A node MUST NOT re-forward a routing message (PROPAGATE, ESCALATE,
        CASCADE, PING) whose ``route`` already contains a hop naming it.
        Loop-detection hops are keyed on :attr:`_node_id` (this node's public
        key), appended by :meth:`_append_self_hop`. These coexist with the
        connection-peer return-path hops that ``handle_message`` records
        (``source == client.peer``): the two occupy disjoint value spaces
        (public keys vs ``name::session_id`` ids), so this check never matches
        a return-path hop, and the response walk-back in
        :meth:`_route_query_response` (which resolves hops against
        ``self.clients``, keyed by connection peers) never resolves a
        node-identity hop. Returns True when this node already appears in the
        route, meaning the message has looped back.
        """
        return any(hop.get("source") == self._node_id
                   for hop in (message.route or []))

    def _append_self_hop(self, payload: HiveMessage) -> None:
        """HIVEMIND-MSG-1 §5: append a hop naming THIS node to ``route`` before
        forwarding a routing message, so a downstream node (or this node, on a
        cycle) can detect the loop.

        The hop is keyed on :attr:`_node_id` (a stable, unique node identity),
        not on the per-connection ``source_peer`` used by return-path hops. A
        fresh route list is built per call so appending never mutates a route
        object aliased by a sibling PROPAGATE/CASCADE branch (the same payload
        object is fanned out to every peer).
        """
        hop = {"source": self._node_id,
               "targets": list(payload.target_peers) or [self._node_id]}
        payload.replace_route(list(payload.route) + [hop])

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
            # kick client for misbehaviour so it stops doing that
            client.disconnect()
            return

        # HIVEMIND-MSG-1 §5 gates *re-forwarding* of a looped message, not local
        # handling. Detect the loop up front, but keep delivering locally below;
        # only the peer fan-out + master-forward at the end are suppressed.
        looped = self._is_routing_loop(message)
        # MSG-1 §5: name ourselves in the route before forwarding (only when we
        # will actually forward — a looped message is not re-stamped)
        if not looped:
            self._append_self_hop(payload)

        # --- local delivery (runs even for a looped message) ---
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

        if message.payload.msg_type == HiveMessageType.PING:
            # PING is mapped and de-duplicated by its own flood_id mechanism
            # (feeds the HiveMapper + emits hive.ping.received before that gate),
            # so it must run on every arrival, looped or not.
            self.handle_ping_message(payload, client)

        # --- forwarding (MSG-1 §5: suppressed for a looped message) ---
        if looped:
            LOG.debug("not re-forwarding PROPAGATE already routed through this "
                      f"node {self._node_id} (MSG-1 §5); route={message.route}")
            return

        # propagate message to other peers
        for peer in self.clients:
            if peer == client.peer:
                continue
            self.clients[peer].send(payload)

        # forward upstream to the master this node relays to (no-op at top level)
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

        # Surface every observed PING on the agent bus (discovery/telemetry).
        # Fires for satellite-originated and flood-cycle pings alike, before the
        # dedup gate below.
        self.agent_protocol.bus.emit(Message("hive.ping.received", {
            "flood_id": flood_id,
            "peer": ping_payload.get("peer"),
            "site_id": ping_payload.get("site_id"),
            "timestamp": ping_payload.get("timestamp"),
        }))

        # Flood-loop prevention: if we already responded to this flood_id, stop
        if not flood_id or flood_id in self._seen_flood_ids:
            return

        # Evict oldest entries when cache is full (FIFO-ish)
        while len(self._seen_flood_ids) >= 1000:
            self._seen_flood_ids.pop()
        self._seen_flood_ids.add(flood_id)

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
            conn.send(own_ping_outer)

    def bind_upstream(self, slave) -> None:
        """Bind a ``HiveMindSlaveProtocol`` as this node's upstream connection,
        turning it into a relay: BROADCAST/PROPAGATE from the upstream master
        are fanned out to downstream clients, and downstream PROPAGATE/ESCALATE
        are forwarded upstream. ``slave`` must already be bound to a bus.
        """
        self._upstream_hm = slave.hm
        slave.hm.on(HiveMessageType.BROADCAST, self.broadcast_from_master)
        slave.hm.on(HiveMessageType.PROPAGATE, self.propagate_from_master)
        slave.hm.on(HiveMessageType.QUERY, self.query_from_master)
        slave.hm.on(HiveMessageType.CASCADE, self.cascade_from_master)

    def broadcast_from_master(self, message: HiveMessage) -> None:
        """Fan a BROADCAST received from the upstream master out to all
        downstream clients."""
        for peer, conn in self.clients.items():
            conn.send(message)

    def propagate_from_master(self, message: HiveMessage) -> None:
        """Fan a PROPAGATE received from the upstream master out to all
        downstream clients."""
        for peer, conn in self.clients.items():
            conn.send(message)

    def escalate_to_master(self, payload: HiveMessage) -> None:
        """Forward an ESCALATE upstream. No-op when this node is the top-level
        master (nothing bound via :meth:`bind_upstream`)."""
        if self._upstream_hm is None:
            return
        msg = HiveMessage(HiveMessageType.ESCALATE, payload=payload)
        # MSG-1 §5: carry the accumulated route on the outer envelope upstream
        msg.replace_route(payload.route)
        self._upstream_hm.emit(msg)

    def propagate_to_master(self, payload: HiveMessage) -> None:
        """Forward a PROPAGATE upstream. No-op when this node is the top-level
        master (nothing bound via :meth:`bind_upstream`)."""
        if self._upstream_hm is None:
            return
        msg = HiveMessage(HiveMessageType.PROPAGATE, payload=payload)
        # MSG-1 §5: carry the accumulated route on the outer envelope upstream
        msg.replace_route(payload.route)
        self._upstream_hm.emit(msg)

    def query_from_master(self, message: HiveMessage) -> None:
        """Fan a QUERY received from the upstream master out to downstream clients."""
        for peer, conn in self.clients.items():
            conn.send(message)

    def query_to_master(self, payload: HiveMessage, metadata: Optional[dict] = None) -> None:
        """Forward a QUERY upstream. No-op at the top-level master."""
        if self._upstream_hm is None:
            return
        self._upstream_hm.emit(HiveMessage(HiveMessageType.QUERY, payload=payload,
                                           metadata=metadata))

    def _build_query_response(self, msg_type: HiveMessageType, response: Message,
                              query_id: str, originator_peer: str,
                              responder_peer: str,
                              route: Optional[list] = None) -> HiveMessage:
        """Wrap a *response* — one streamed ``speak``, or the
        ``QUERY_STREAM_END`` control message that terminates the stream — as a
        QUERY/CASCADE response HiveMessage."""
        inner = HiveMessage(HiveMessageType.BUS, payload=response)
        msg = HiveMessage(
            msg_type, payload=inner,
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

    def _admit_for_query(self, message: Message,
                         client: HiveMindClientConnection) -> Optional[Message]:
        """Policy-admit a QUERY/CASCADE inner bus message without injecting it
        (the agent's ``natural_language_query`` does the answering). Returns the
        admitted Message, or None if unauthorized / policy-denied."""
        if not client.authorize(message):
            LOG.warning(f"{client.peer} sent an unauthorized QUERY/CASCADE message")
            return None
        message = self._install_client_session(message, client)
        if message.context.get("destination") is None:
            message.context["destination"] = "skills"
        verdict = self.policy_chain.review(message, client)
        if verdict.denied:
            LOG.info(f"policy denied QUERY '{message.msg_type}' from "
                     f"{client.peer}: {verdict.code} ({verdict.reason})")
            self._send_policy_denied(client, message, verdict)
            return None
        message.context["peer"] = message.context["source"] = client.peer
        self.policy_chain.observe(message, client)
        return message

    def _answer_query_locally(self, message: HiveMessage,
                              client: HiveMindClientConnection, query_id: str,
                              originator_peer: str, msg_type: HiveMessageType,
                              route, send_fn) -> bool:
        """Stream a local-agent answer for a QUERY/CASCADE request. Extracts the
        natural-language utterance, runs it through the policy admission gate,
        then streams the agent's answer chunks via ``send_fn`` (one ``speak``
        per chunk) followed by a ``QUERY_STREAM_END`` end-of-stream control message. Returns
        True if the agent answered (caller stops), False if it declined (caller
        escalates)."""
        inner = message.payload
        if inner.msg_type != HiveMessageType.BUS or not isinstance(inner.payload, Message):
            return False
        bus_msg = inner.payload
        if bus_msg.msg_type != "recognizer_loop:utterance":
            return False  # QUERY/CASCADE answer natural-language utterances only
        admitted = self._admit_for_query(bus_msg, client)
        if admitted is None:
            return False
        utts = admitted.data.get("utterances") or []
        utterance = utts[0] if utts else ""
        lang = (admitted.data.get("lang") or admitted.context.get("lang")
                or self.default_lang)
        if not utterance:
            return False
        answered = False
        try:
            for chunk in self.agent_protocol.answer_query(utterance, lang, client=client):
                if chunk is None:
                    break
                answered = True
                resp = Message("speak", {"utterance": chunk, "lang": lang},
                               {"query_id": query_id})
                send_fn(self._build_query_response(
                    msg_type, resp, query_id, originator_peer, self.peer,
                    route=route))
        except NotImplementedError:
            return False  # agent has no NL backend -> escalate
        if answered:
            send_fn(self._build_query_response(
                msg_type, Message(QUERY_STREAM_END, {}), query_id,
                originator_peer, self.peer, route=route))
        return answered

    def _route_query_response(self, message: HiveMessage,
                              client: HiveMindClientConnection):
        """Route a QUERY response downstream toward its originator (direct
        client if connected here, else fan to downstream peers)."""
        metadata = message.metadata or {}
        originator_peer = metadata.get("originator_peer", "")
        # CASCADE disambiguation: collect responses for a select callback at
        # the originating node, letting it pick a winner progressively.
        if (message.msg_type == HiveMessageType.CASCADE
                and self.cascade_select_callback is not None
                and originator_peer in self.clients):
            query_id = metadata.get("query_id", "")
            if query_id not in self._pending_cascades:
                while len(self._pending_cascades) >= 256:  # bound the collector map
                    self._pending_cascades.pop(next(iter(self._pending_cascades)))
                self._pending_cascades[query_id] = CascadeCollector(
                    query_id=query_id, originator_peer=originator_peer)
            collector = self._pending_cascades[query_id]
            collector.add_response(message)
            bus = self.get_bus(self.clients[originator_peer])
            try:
                selected = self.cascade_select_callback(query_id, collector.responses)
                if selected is not None:
                    bus.emit(selected)
                    del self._pending_cascades[query_id]
            except Exception:
                LOG.exception(f"cascade_select_callback error for query_id={query_id}")
            return
        # Default routing: forward toward the originator
        if originator_peer in self.clients:
            self.clients[originator_peer].send(message)
            return
        # route-aware return: send to the downstream hop on the path back to
        # the originator (from the request's recorded route) instead of flooding
        for hop in reversed(message.route or []):
            src = hop.get("source")
            if src and src != client.peer and src in self.clients:
                self.clients[src].send(message)
                return
        # unknown return path: fan downstream (excluding the sender) as a last resort
        for peer in self.clients:
            if peer == client.peer:
                continue
            self.clients[peer].send(message)

    def handle_query_message(self, message: HiveMessage,
                             client: HiveMindClientConnection):
        """QUERY — like ESCALATE but expects a response. Request: try the local
        agent; if answered, reply downstream; else escalate upstream (or return
        a no-answer error at the top). Response: route downstream to originator.
        """
        LOG.info(f"Received QUERY from: {client.peer}")
        metadata = message.metadata or {}
        if metadata.get("is_response", False):
            self._route_query_response(message, client)
            return

        payload = self._unpack_message(message, client)
        if not client.can_escalate:
            LOG.warning("Received QUERY from client without escalate permission")
            if self.illegal_callback:
                self.illegal_callback(payload)
            client.disconnect()
            return

        query_id = metadata.get("query_id", str(uuid.uuid4()))
        originator_peer = metadata.get("originator_peer", client.peer)
        bus = self.get_bus(client)
        bus.emit(Message("hive.query.received",
                         {"query_id": query_id, "originator_peer": originator_peer},
                         {"source": client.peer}))

        if self._answer_query_locally(message, client, query_id, originator_peer,
                                      HiveMessageType.QUERY, message.route,
                                      client.send):
            return

        if self._upstream_hm is not None:
            self.query_to_master(payload, metadata)
        else:
            error_bus = Message("hive.query.timeout",
                                {"query_id": query_id, "error": "no_answer"})
            client.send(self._build_query_response(
                HiveMessageType.QUERY, error_bus, query_id,
                originator_peer, self.peer, route=message.route))

    def cascade_from_master(self, message: HiveMessage) -> None:
        """Fan a CASCADE received from the upstream master out to downstream clients."""
        for peer, conn in self.clients.items():
            conn.send(message)

    def cascade_to_master(self, payload: HiveMessage, metadata: Optional[dict] = None) -> None:
        """Forward a CASCADE upstream. No-op at the top-level master."""
        if self._upstream_hm is None:
            return
        msg = HiveMessage(HiveMessageType.CASCADE, payload=payload,
                          metadata=metadata)
        # MSG-1 §5: carry the accumulated route on the outer envelope upstream
        msg.replace_route(payload.route)
        self._upstream_hm.emit(msg)

    def handle_cascade_message(self, message: HiveMessage,
                               client: HiveMindClientConnection):
        """CASCADE — like PROPAGATE but every node may answer. Request: try the
        local agent, forward to all other peers + upstream, relay responses
        (collected for disambiguation at the originator). Response: route
        downstream toward the originator."""
        LOG.info(f"Received CASCADE from: {client.peer}")
        metadata = message.metadata or {}
        if metadata.get("is_response", False):
            self._route_query_response(message, client)
            return

        payload = self._unpack_message(message, client)
        if not client.can_propagate:
            if self.illegal_callback:
                self.illegal_callback(payload)
            client.disconnect()
            return

        # HIVEMIND-MSG-1 §5 gates re-forwarding of a looped message, not local
        # handling; suppress only the fan-out + master-forward at the end.
        looped = self._is_routing_loop(message)
        # MSG-1 §5: name ourselves in the route before forwarding
        if not looped:
            self._append_self_hop(payload)

        query_id = metadata.get("query_id", str(uuid.uuid4()))
        originator_peer = metadata.get("originator_peer", client.peer)
        bus = self.get_bus(client)
        bus.emit(Message("hive.cascade.received",
                         {"query_id": query_id, "originator_peer": originator_peer},
                         {"source": client.peer}))

        # local delivery: this node answers the cascade (runs even when looped)
        self._answer_query_locally(
            message, client, query_id, originator_peer, HiveMessageType.CASCADE,
            message.route, lambda hm: self._route_query_response(hm, client))

        # MSG-1 §5: do not re-forward a looped CASCADE
        if looped:
            LOG.debug("not re-forwarding CASCADE already routed through this "
                      f"node {self._node_id} (MSG-1 §5); route={message.route}")
            return

        cascade_fwd = HiveMessage(HiveMessageType.CASCADE, payload=payload,
                                  metadata=metadata)
        # MSG-1 §5: carry the accumulated route (incl. our self-hop) on the
        # outer envelope so downstream nodes can detect the loop
        cascade_fwd.replace_route(payload.route)
        for peer in self.clients:
            if peer == client.peer:
                continue
            self.clients[peer].send(cascade_fwd)
        self.cascade_to_master(payload, metadata)

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
            # kick client for misbehaviour so it stops doing that
            client.disconnect()
            return

        # HIVEMIND-MSG-1 §5 gates re-forwarding of a looped message, not local
        # handling; suppress only the upstream forward at the end.
        looped = self._is_routing_loop(message)
        # MSG-1 §5: name ourselves in the route before forwarding
        if not looped:
            self._append_self_hop(payload)

        # --- local delivery (runs even for a looped message) ---
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

        # --- forwarding (MSG-1 §5: suppressed for a looped message) ---
        if looped:
            LOG.debug("not re-forwarding ESCALATE already routed through this "
                      f"node {self._node_id} (MSG-1 §5); route={message.route}")
            return

        # escalate up the chain to the master this node relays to (no-op at top level)
        self.escalate_to_master(payload)

    def handle_intercom_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ) -> bool:
        """Handle an INTERCOM frame.

        Returns True when the frame is consumed by this node and MUST NOT be
        relayed any further - either because the inner message was dispatched
        locally, or because the frame was rejected (a refused message is
        dropped, never forwarded to peers or escalated upstream).

        Returns False only when the frame is not ours to consume and the
        caller should keep relaying it.
        """
        # if the message targets us, send it to internal bus
        k = message.target_public_key
        if k and k != self.identity.public_key:
            # not for us, keep relaying
            return False

        pload = message.payload
        if isinstance(pload, dict) and "ciphertext" in pload:
            try:
                ciphertext = pybase64.b64decode(pload["ciphertext"])
                signature = pload.get("signature")

                # HIVEMIND-CRYPTO-1 §5 - the origin signature MUST verify
                # against the TOFU-pinned public key (pinned from the
                # client's HELLO). Without a pinned/known pubkey, or without
                # a signature, the origin cannot be authenticated at all -
                # fail closed and drop rather than dispatch unverified.
                # A rejection returns True: the frame is consumed here, it is
                # not relayed to peers nor escalated upstream.
                pub = self.trusted_pubkeys.get(client.key) or client.pub_key
                if not pub:
                    LOG.warning(f"INTERCOM from {client.peer} has no pinned/known "
                                f"public key: dropping unverifiable origin")
                    return True
                if not signature:
                    LOG.warning(f"INTERCOM from {client.peer} has no signature: "
                                f"dropping unverifiable origin")
                    return True

                try:
                    verified = verify_RSA(pub, ciphertext, pybase64.b64decode(signature))
                except Exception:
                    verified = False
                if not verified:
                    LOG.error(f"INTERCOM signature verification failed for "
                              f"{client.peer}: dropping forged/mismatched message")
                    return True
                # first verified sighting pins the key for this listener's lifetime
                self.trusted_pubkeys.setdefault(client.key, pub)

                private_key = load_RSA_key(self.identity.private_key)

                decrypted: str = decrypt_RSA(private_key, ciphertext).decode("utf-8")
                inner = HiveMessage.deserialize(decrypted)
            except:
                if k:
                    # explicitly addressed to us and undecryptable: drop it
                    LOG.error("failed to decrypt message!")
                    return True
                LOG.debug("failed to decrypt message, not for us")
                return False
        elif isinstance(pload, HiveMessage):
            inner = pload
        else:
            # unencrypted intercom: the inner HiveMessage is carried as a
            # plain dict. Deserialize it so it is dispatched on its OWN
            # (inner) msg_type instead of the outer INTERCOM type, which
            # matches no branch below and silently drops the message.
            inner = HiveMessage.deserialize(pload)

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
    def _install_client_session(self, message: Message,
                                 client: HiveMindClientConnection):
        """Copy the client's serialised session onto an inbound bus message.

        Must run BEFORE the policy chain so policies see the canonical
        session (skill/intent injection mutations will land on this
        dict).

        Skill / intent / message-type blacklist injection moved to
        ``OVOSAgentPolicy`` in ``hivemind-ovos-agent-plugin`` (see #85).
        This method only handles the session-rewrite half of what used
        to be ``_update_blacklist``: copy ``client.sess.serialize()`` onto
        the message, taking care not to reattach a stale pipeline.

        Per SESSION-1 §2: any session field carrying JSON ``null`` is
        malformed and MUST be treated as absent (not preserved). This
        method strips null-valued fields from the session before writing
        it to the message context so downstream consumers never see them.
        """
        raw_session = message.context.get("session") or {}
        session = client.sess.serialize()
        if not isinstance(raw_session, dict) or raw_session.get("pipeline") is None:
            # Each bus message owns its outbound pipeline; do not reattach
            # one from an earlier message. Per SESSION-1 §2 an explicit
            # null pipeline is malformed and treated as absent; strip it
            # here explicitly (serializers may render a None pipeline as
            # [], which the generic null-strip below would not catch).
            session.pop("pipeline", None)
        # SESSION-1 §2: strip null-valued fields — null is malformed, treat as absent.
        session = {k: v for k, v in session.items() if v is not None}
        message.context["session"] = session
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
        message = self._install_client_session(message, client)
        if message.msg_type == "speak":
            message.context["destination"] = ["audio"]  # make audible, this is injected "speak" command
        elif message.context.get("destination") is None:
            message.context["destination"] = "skills"  # ensure not treated as a broadcast

        # policy admission chain — issue #85
        verdict = self.policy_chain.review(message, client)
        if verdict.denied:
            LOG.info(f"policy denied '{message.msg_type}' from {client.peer}: "
                     f"{verdict.code} ({verdict.reason})")
            self._send_policy_denied(client, message, verdict)
            return

        # send client message to internal mycroft bus
        LOG.info(f"Forwarding message '{message.msg_type}' to agent bus from client: {client.peer}")
        message.context["peer"] = message.context["source"] = client.peer
        message.context["source"] = client.peer

        bus = self.get_bus(client)
        bus.emit(message)

        self.policy_chain.observe(message, client)

        if self.agent_bus_callback:
            self.agent_bus_callback(message)

    def _send_policy_denied(self, client: HiveMindClientConnection,
                             message: Message, verdict) -> None:
        """Inform a client that an admission policy denied their message."""
        payload = Message(
            "hive.policy.denied",
            {
                "denied_type": getattr(message, "msg_type", None),
                "code": verdict.code,
                "reason": verdict.reason,
                "data": verdict.data,
            },
            {"source": "hivemind-core", "destination": client.peer},
        )
        try:
            client.send(HiveMessage(HiveMessageType.BUS, payload=payload))
        except Exception:
            LOG.exception(f"failed to send hive.policy.denied to {client.peer}")

    def handle_client_shared_bus(self, message: Message, client: HiveMindClientConnection):
        # this message is going inside the client bus
        # take any metrics you need
        LOG.info("Monitoring bus from client: " + client.peer)
        if self.shared_bus_callback:
            self.shared_bus_callback(message)
