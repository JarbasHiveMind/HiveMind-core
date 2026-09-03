# hivemind-core
# Copyright (C) 2026 Casimiro Ferreira
# SPDX-License-Identifier: Apache-2.0
import copy
import dataclasses
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Union, List, Dict, Optional, Callable, Literal

import pybase64
from ovos_bus_client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_bus_client.session import MalformedSession, Session
from ovos_plugin_manager.transformer_services import (DialogTransformersService,
                                                      MetadataTransformersService,
                                                      UtteranceTransformersService)
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG
from hivemind_core.config import get_server_config
from hivemind_bus_client.identity import NodeIdentity
from hivemind_bus_client.message import HiveMessage, HiveMessageType, HiveMindBinaryPayloadType
from hivemind_bus_client.serialization import BINARY_ENCODABLE_TYPES, decode_bitstring, get_bitstring
from hivemind_bus_client.encryption import (SupportedEncodings, SupportedCiphers,
                                            decrypt_from_json, encrypt_as_json,
                                            decrypt_bin, encrypt_bin,
                                            hybrid_decrypt,
                                            _norm_encoding, _norm_cipher)
try:
    from hivemind_bus_client.noise import (NOISE_SUPPORTED, NOISE_PATTERNS, NOISE_SUITES,
                                           NOISE_PATTERN_KK, NoiseTransport,
                                           NoiseHandshakeFailed, NoiseTransportFailed,
                                           build_prologue, noise_protocol_name,
                                           start_noise_handshake, derive_psk)
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

    def derive_psk(*args, **kwargs):  # pragma: no cover
        raise NoiseHandshakeFailed("protocol v3 (Noise) support unavailable")
from hivemind_core.database import ClientDatabase
from hivemind_bus_client.hive_map import FloodIdCache, HiveMapper
from hivemind_plugin_manager.protocols import AgentProtocol, BinaryDataHandlerProtocol, ClientCallbacks
from hivemind_plugin_manager.database import Client
from hivemind_plugin_manager.policy import PolicyPlugin
from hivemind_core.policy import (BACKEND_UNAVAILABLE, MALFORMED_PAYLOAD,
                                  PolicyChain)
from poorman_handshake import HandShake, PasswordHandShake
from poorman_handshake.asymmetric.utils import decrypt_RSA, load_RSA_key, verify_RSA
from Cryptodome.PublicKey import RSA

#: Stdlib logger used ONLY in ``HiveMindClientConnection.send()``'s per-peer hot
#: path. ``ovos_utils.log.LOG.debug`` is a classmethod that calls
#: ``inspect.stack()`` before checking the log level, so a *suppressed* call
#: still costs 3+ orders of magnitude more than stdlib, which checks the level
#: first. Measured at ~570ms of ~816ms in a 1000-peer fan-out. Everywhere else
#: in this file keeps using ovos ``LOG`` on purpose, so it routes into OVOS's
#: logging setup — do not "fix" this one back to match.
_log = logging.getLogger(__name__)

#: HIVEMIND-MSG-1 §4: the payload of these message types IS a nested
#: ``HiveMessage``. Every other type carries a bus ``Message``, binary data or
#: a plain dict.
#:
#: The list is documentation only — ``_payload_is_usable`` does NOT use it.
#: Choosing the guarded types by spec section is what let the first version of
#: the guard through with holes in it: ``SHARED_BUS`` rebuilds a bus
#: ``Message`` from ``payload["type"]`` (``handle_client_shared_bus``) and is
#: not in this list, and the wrapper handlers dereference the payload of the
#: payload as well. Every type is checked instead — see ``_payload_is_usable``.
WRAPPER_TYPES = (HiveMessageType.PROPAGATE, HiveMessageType.BROADCAST,
                 HiveMessageType.ESCALATE, HiveMessageType.QUERY,
                 HiveMessageType.CASCADE)


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

# Retention window (seconds) for participation-binding state (MSG-1 §5.2): how
# long a node remembers a request it saw so it can route the matching answer.
# Kept comfortably above a query's expected round-trip; a later answer is a
# genuinely stale one and is dropped. Time source is time.monotonic().
OUTSTANDING_QUERY_TTL = 300.0
# Hard cap on distinct outstanding queries, mirroring the _pending_cascades
# bound, so a flood of unique query_ids cannot grow the store without limit.
OUTSTANDING_QUERY_MAX = 256


def _non_negative_float(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _configured_min_protocol_version() -> ProtocolVersion:
    """The operator-configured protocol floor (HIVEMIND-WIRE-1 §2); default 2
    refuses the oldest json-only / no-binary clients. An unparseable config
    value falls back to that same default."""
    try:
        return ProtocolVersion(int(get_server_config().get("min_protocol_version", 2)))
    except (TypeError, ValueError, KeyError):
        return ProtocolVersion.TWO


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
    disconnect: Callable[..., None]

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
    can_broadcast: bool = True
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

    # Appended to ``peer`` when another live connection already owns the same
    # ``name::session_id`` string. See ``handle_hello_message``.
    _peer_suffix: str = field(default="", init=False, repr=False)

    # Per-connection nonce, minted lazily once and stable for the
    # connection's life. Namespaces the client-declared session_id — see
    # ``layer1_session_id`` below (HIVEMIND-BRIDGE-1 §4).
    _conn_nonce: str = field(default="", init=False, repr=False)

    # Serialises ``send``. The IOLoop thread, the ovos messagebus thread and
    # the upstream slave thread all send on the same connection, and a v3
    # Noise frame is only decryptable in the order its nonce was assigned, so
    # encryption and enqueueing must happen as one atomic step.
    #
    # Re-entrant because a synchronous in-process transport (the hivescope
    # loopback) delivers to the peer from inside ``send_msg`` and the peer
    # answers on the same thread. That nested send always encrypts after the
    # outer frame was handed over, so it cannot invert the nonce sequence.
    _send_lock: threading.RLock = field(default_factory=threading.RLock,
                                        init=False, repr=False)

    @property
    def conn_nonce(self) -> str:
        """Per-connection nonce, minted lazily on first use and stable for
        the connection's life."""
        if not self._conn_nonce:
            self._conn_nonce = uuid.uuid4().hex
        return self._conn_nonce

    @property
    def session_namespace(self) -> str:
        """A DURABLE, identity-scoped namespace token for this client's
        Layer-1 sessions (HIVEMIND-BRIDGE-1 §4).

        Unlike :attr:`conn_nonce`, which is reminted on every reconnect,
        this token is derived from the client's durable DB identity, so a
        satellite that drops and reconnects keeps the same namespace: a
        session minted before the drop stays routable afterwards, and a
        scheduler-replayed message carrying that old session_id remains
        deliverable.

        The token is ``sha256(f"{hub_salt}:{client_id}")[:16]`` where
        ``client_id`` is the durable DB row id (via :meth:`resolve_user`,
        which already caches with a TTL) and ``hub_salt`` is the hub's
        persistent node public key (:attr:`NodeIdentity.public_key`, the
        same identity the node persists on disk), so the namespace also
        survives a HUB restart. The token IDENTIFIES, it does not
        AUTHENTICATE: possession grants nothing and admission still runs
        the ACL. It is derived from the durable client identity, NOT the
        secret access key (session_ids are visible to every bus observer),
        and hub-salted so the same client is not linkable across hubs. The
        salt also hides the small integer client_id, so the token is not
        enumerable.

        Falls back to :attr:`conn_nonce` when no DB is reachable or the
        client_id cannot be resolved (unauthenticated/edge), so nothing
        crashes — at the cost of losing reconnect durability for that
        connection.
        """
        db = getattr(getattr(self, "hm_protocol", None), "db", None)
        client_id = None
        if db is not None:
            try:
                user = self.resolve_user(db)
                client_id = getattr(user, "client_id", None)
            except Exception:
                LOG.debug("session_namespace: failed to resolve user; "
                          "falling back to conn_nonce", exc_info=True)
        if client_id is None:
            LOG.debug("session_namespace: no durable client_id; "
                      "falling back to per-connection nonce")
            return self.conn_nonce
        identity = getattr(getattr(self, "hm_protocol", None), "identity", None)
        hub_salt = getattr(identity, "public_key", None) or ""
        return hashlib.sha256(
            f"{hub_salt}:{client_id}".encode()).hexdigest()[:16]

    @property
    def layer1_session_id(self) -> str:
        """The orchestrator-side (Layer-1) session id for this connection's
        CURRENT declared session — the durable ``session_namespace``
        namespaces the client-declared session_id, so two connections that
        chose the same name get distinct Layer-1 sessions (HIVEMIND-BRIDGE-1
        §4) while one connection's distinct declared sessions (a re-HELLO, or
        a bridge like baresip that mints a fresh session_id per call on one
        connection) stay distinct too — session travels per message, the
        client declares it.

        The namespace is identity-scoped (see ``session_namespace``), so this
        id — and the disconnect notification that carries it — is stable
        across a reconnect: it matches the id ``_install_client_session``
        stamped on the connection's inbound bus messages."""
        return f"{self.session_namespace}:{self.sess.session_id}"

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
        # Reuse the node's already-imported RSA key (loaded once in
        # HiveMindListenerProtocol.__post_init__) instead of re-reading and
        # re-validating the PEM file on every connection — PyCryptodome's
        # validation of a 2048-bit key measured 35-58ms, and it used to run
        # inline on the IOLoop thread serving every connected client. Only
        # the immutable ``private_key`` is shared; the HandShake instance
        # itself is fresh per connection, since ``target_key``/``secret``
        # hold per-peer session state that must never leak between clients.
        if not self.handshake:
            self.handshake = HandShake.__new__(HandShake)
            self.handshake.private_key = self.hm_protocol.identity_rsa_key
            self.handshake.target_key = None
            self.handshake.secret = None

    @property
    def peer(self) -> str:
        # friendly id that ovos components can use to refer to this connection
        # this is how ovos refers to connected nodes in message.context
        return f"{self.name}::{self.sess.session_id}{self._peer_suffix}"

    def send(self, message: HiveMessage, plaintext: Optional[str] = None):
        """Send ``message`` to this peer.

        ``plaintext`` lets a fan-out caller pass a pre-serialized
        ``message.serialize()`` result, computed once for the whole fan-out
        instead of once per peer (serialization is not cheap and does not
        depend on the peer). Encryption still happens per peer below, since
        each connection has its own crypto state.

        The lock is held across encrypt *and* enqueue. The Noise transport and
        the AES counters are per-connection mutable state, so releasing it
        between the two would let a second thread encrypt against the same
        counter and interleave frames on the wire.
        """
        with self._send_lock:
            is_bin = message.msg_type == HiveMessageType.BINARY
            if not is_bin and message.msg_type == HiveMessageType.BUS:
                _payload_type = (message.payload.get("type")
                                 if isinstance(message.payload, dict)
                                 else message.payload.msg_type)
                _log.debug("mycroft_type %s", _payload_type)

                # OUTBOUND half of the BRIDGE-1 §4 session NAT, symmetric with
                # the inbound _install_client_session / _layer1_session_id: the
                # bus stamps every inbound message with the Layer-1 id
                # f"{session_namespace}:{declared}", so on the way back to the
                # client we strip this connection's namespace prefix and restore
                # the client's own declared session_id. A client only ever sees
                # its own declared ids; the internal namespace never crosses the
                # wire. Living in core (the single per-client delivery choke
                # point) means every agent/binary protocol plugin inherits it
                # instead of each having to reimplement the un-NAT.
                unnatted = self._unnat_outbound_session(message)
                if unnatted is not message:
                    # A per-peer deepcopy was made because the prefix matched;
                    # the input ``message`` is shared across a fan-out and was
                    # NOT mutated. Any ``plaintext`` passed in was serialized
                    # from the still-NATted shared message and is wrong for this
                    # peer, so drop it and reserialize the un-NATted copy below.
                    message = unnatted
                    plaintext = None

            _log.debug("sending to %s: %s", self.peer, message.msg_type)

            # WIRE-1 §4.3: a type with no assigned 5-bit code (INTERCOM) travels
            # as a text frame even on a connection that negotiated binarize. The
            # receiver accepts both forms on the same connection.
            binarize = ((self.binarize or is_bin)
                        and message.msg_type in BINARY_ENCODABLE_TYPES)

            if self.noise_transport is not None:
                # protocol v3: every message (HELLO/HANDSHAKE included) is a Noise
                # transport message — there is no cleartext v3 session (§3.4.5)
                if binarize:
                    payload = get_bitstring(hive_type=message.msg_type,
                                            payload=message.payload,
                                            hivemeta=message.metadata,
                                            binary_type=message.bin_type).bytes
                else:
                    payload = plaintext if plaintext is not None else message.serialize()
                self.send_msg(self.noise_transport.encrypt_frame(payload), True)
                return

            if self.crypto_key and message.msg_type not in [
                HiveMessageType.HANDSHAKE,
                HiveMessageType.HELLO,
            ]:
                if binarize:
                    payload = get_bitstring(hive_type=message.msg_type,
                                            payload=message.payload,
                                            hivemeta=message.metadata,
                                            binary_type=message.bin_type).bytes
                    _log.debug("unencrypted binary payload size: %d bytes", len(payload))
                    payload = encrypt_bin(key=self.crypto_key, plaintext=payload, cipher=self.cipher)
                    is_bin = True
                else:
                    plaintext = plaintext if plaintext is not None else message.serialize()
                    _log.debug("unencrypted payload size: %d bytes", len(plaintext))
                    payload = encrypt_as_json(
                        key=self.crypto_key, plaintext=plaintext,
                        cipher=self.cipher, encoding=self.encoding
                    )  # json string
                _log.debug("encrypted payload size: %d bytes", len(payload))
            else:
                payload = plaintext if plaintext is not None else message.serialize()
                _log.debug("sent unencrypted!")

            self.send_msg(payload, is_bin)

    def _unnat_outbound_session(self, message: HiveMessage) -> HiveMessage:
        """Restore this connection's declared session_id on an outbound BUS
        message, undoing the inbound NAT (BRIDGE-1 §4).

        The inbound boundary rewrites a non-admin client's declared session_id
        to ``f"{session_namespace}:{declared}"``. Here we recover ``declared``
        by stripping this connection's namespace prefix. The payload is either
        an ``ovos_bus_client`` ``Message`` or a raw dict (mirroring the
        dict-vs-Message handling in :meth:`send`).

        Returns a per-peer deepcopy with the session_id restored when the
        prefix matches, otherwise the input ``message`` unchanged. The input is
        shared across a fan-out to multiple peers and is never mutated. When the
        session id carries no namespace prefix (an admin bare id, another
        client's namespace, or no session at all) the message is left as-is.
        """
        payload = message.payload
        if isinstance(payload, dict):
            session = (payload.get("context") or {}).get("session")
        else:
            session = getattr(payload, "context", {}).get("session")
        sid = session.get("session_id") if isinstance(session, dict) else None
        prefix = f"{self.session_namespace}:"
        if not isinstance(sid, str) or not sid.startswith(prefix):
            return message
        declared = sid[len(prefix):]
        if not declared:
            return message
        out = copy.deepcopy(message)
        if isinstance(out.payload, dict):
            out.payload["context"]["session"]["session_id"] = declared
        else:
            out.payload.context["session"]["session_id"] = declared
        return out

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
                self.disconnect(1008, "non-Noise message received on a protocol v3 session")
                raise NoiseTransportFailed(
                    "non-Noise message received on a protocol v3 session")
            try:
                payload = self.noise_transport.decrypt_frame(payload)
            except NoiseTransportFailed:
                LOG.error(f"rejecting invalid Noise transport message from "
                          f"{self.peer} (tampered, replayed or out-of-order), "
                          "disconnecting")
                self.disconnect(1008, "invalid Noise transport message (tampered, replayed or out-of-order)")
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
            self.disconnect(1008, "unencrypted message rejected: crypto is required")
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
    """Collects CASCADE responses for a given query_id at the originator.

    HIVEMIND-AGENT-1 §4.3: collected responses are keyed by query identifier
    **and responder**. The query identifier is this collector; the responder is
    :attr:`_by_responder`. Every node answering a CASCADE streams its own chunk
    sequence, so one responder's chunks accumulate into one
    :class:`CascadeResponse` and two responders never share an entry.
    """
    query_id: str
    originator_peer: str
    responses: List[CascadeResponse] = field(default_factory=list)
    # responder_peer -> its entry in ``responses``; ``responses`` stays a list
    # so a select callback sees responders in order of first arrival.
    _by_responder: Dict[str, CascadeResponse] = field(default_factory=dict)

    def add_response(self, message: HiveMessage) -> 'CascadeResponse':
        meta = message.metadata or {}
        responder = meta.get("responder_peer", "unknown")
        candidate = CascadeResponse(
            responder_peer=responder,
            responder_site_id=meta.get("responder_site_id", ""),
            metadata=meta,
        )
        # setdefault is a single atomic dict op under the GIL, so two threads
        # racing on the same responder can never both win: whichever entry
        # setdefault returns is the one and only entry for that responder.
        resp = self._by_responder.setdefault(responder, candidate)
        if resp is candidate:
            self.responses.append(resp)
        inner = message.payload
        if isinstance(inner, HiveMessage) and inner.msg_type == HiveMessageType.BUS:
            bus_msg = inner.payload
            if isinstance(bus_msg, Message):
                resp.messages.append(bus_msg)
        return resp


@dataclass
class HiveMindListenerProtocol:
    agent_protocol: Optional[AgentProtocol] = None
    binary_data_protocol: Optional[BinaryDataHandlerProtocol] = None
    # Human-readable label for logs only. ``service.py`` never sets it, so
    # every deployed node shares this default — it identifies nothing. Use
    # ``_node_id`` (the node public key) for provenance and addressing.
    peer: str = "master:0.0.0.0"

    require_crypto: bool = True  # throw error if crypto key not available
    handshake_enabled: bool = True  # generate a key per session if not pre-shared
    identity: NodeIdentity = dataclasses.field(default_factory=NodeIdentity)
    db: ClientDatabase = dataclasses.field(default_factory=ClientDatabase)
    callbacks: ClientCallbacks = dataclasses.field(default_factory=ClientCallbacks)

    hive_mapper: HiveMapper = dataclasses.field(default_factory=HiveMapper)
    policy_chain: Optional[PolicyChain] = None

    # Throttle state for the mesh-wide responsive PING flood. Both are
    # declared as fields with plain (immutable) defaults, not just assigned in
    # __post_init__, so that a test fixture built with ``object.__new__``
    # finds working values instead of raising AttributeError on the ping path.
    # __post_init__ still overwrites ping_flood_interval from config, so
    # operator config keeps winning.
    # Backing field for the ``_pending_cascades_lock`` property below. A
    # plain __post_init__ assignment left every object.__new__ fixture
    # raising AttributeError the first time a cascade or query was routed.
    _cascades_lock: Optional[threading.Lock] = field(default=None, init=False, repr=False)
    # Participation-binding state (MSG-1 §5.2): (originator_peer, query_id) ->
    # monotonic insert time for every request this node admitted or forwarded.
    # An is_response QUERY/CASCADE is only routed when a matching entry exists,
    # which is what proves this node saw the request and holds a return path.
    # Backing fields with None defaults (class attributes) so a fixture built
    # with ``object.__new__`` finds them, and the properties build the real
    # store/lock lazily — the same treatment as the flood caches and the
    # cascade lock above.
    _outstanding_queries_store: Optional[dict] = field(default=None, init=False, repr=False)
    _outstanding_query_lock: Optional[threading.Lock] = field(default=None, init=False, repr=False)
    # Backing field for the ``_forwarded_flood_ids`` property below. Same
    # treatment as the other flood caches: a mutable FloodIdCache cannot be a
    # class-level default without every node sharing one, so the default is
    # None and the property builds one per instance on first access.
    _forwarded_flood_cache: Optional[FloodIdCache] = field(default=None, init=False, repr=False)
    # Backing field for ``trusted_pubkeys``. handle_client_disconnected now
    # sweeps the TOFU pin store on every disconnect, so a bypass-built
    # fixture reaches it too.
    _trusted_pubkeys: Optional[dict] = field(default=None, init=False, repr=False)
    _last_ping_flood: float = field(default=0.0, init=False, repr=False)
    ping_flood_interval: float = field(default=30.0, init=False)

    # OVOS transformer pipelines for the text/bus path.
    # Config-gated and opt-in via the utterance_transformers /
    # metadata_transformers / dialog_transformers blocks in server.json;
    # empty chains are no-ops.
    utterance_transformers: Optional[UtteranceTransformersService] = None
    metadata_transformers: Optional[MetadataTransformersService] = None
    dialog_transformers: Optional[DialogTransformersService] = None

    # Store-and-forward mailbox, bound at startup when the optional
    # hivemind-rendezvous package is installed and rendezvous is enabled
    # (see HiveMindService._start_rendezvous). None on every ordinary node,
    # which is what makes RENDEZVOUS answer "not_a_rendezvous_node".
    # A dataclass field, so an instance built with ``object.__new__`` in a
    # test fixture still finds the default instead of raising AttributeError.
    mailbox: Optional[object] = field(default=None, repr=False)

    # Interval (seconds) between persisted last-seen updates for the same
    # client, read from config in __post_init__ (which always wins over this
    # default). Declared as a field — not just a __post_init__ assignment —
    # so a test fixture built with ``object.__new__`` still finds a working
    # value here instead of raising AttributeError.
    last_seen_update_interval: float = field(default=0.0, init=False)
    # Cache for the node's RSA identity key (see identity_rsa_key property).
    # Stays None here: constructing HiveMindListenerProtocol must stay cheap
    # and must not touch the key file, since embedders and tests routinely
    # build one with a placeholder ``identity`` and never open a connection.
    # A dataclass field so the default is a real class attribute, present
    # even on an instance built with ``object.__new__``.
    _identity_rsa_key: Optional[RSA.RsaKey] = field(default=None, init=False, repr=False)
    # Backing store for the ``_seen_flood_ids`` property below. Must stay a
    # field (not a plain __post_init__ assignment) so its ``None`` default is
    # a class attribute visible to instances built with ``object.__new__``.
    # It cannot be the ``FloodIdCache`` itself as a class-level default —
    # that would share one flood cache across every node — so the property
    # lazily creates one FloodIdCache per instance on first access instead.
    _flood_id_cache: Optional[FloodIdCache] = field(default=None, init=False, repr=False)

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
        # Derived Noise PSKs, keyed by the client password (see noise_psk
        # below). Never logged and never exposed on any wire or error path.
        self._noise_psks: "OrderedDict[tuple, bytes]" = OrderedDict()
        self.clients = {}
        # TOFU pinning store for INTERCOM origin authentication
        # (HIVEMIND-CRYPTO-1 §5). Maps a client's access key to the PEM
        # public key it presented; once pinned, INTERCOM signatures from that
        # client MUST verify against the pinned key. In-memory for now — pins
        # last for the lifetime of this listener (the Client DB model has no
        # pubkey column yet).
        self._trusted_pubkeys = {}  # client.key -> PEM public key
        # Already-answered PING floods (MSG-1 §4). Set-like, FIFO-evicting:
        # a dedup miss re-triggers a whole flood, so an eviction that drops a
        # live flood_id amplifies the very traffic this cache exists to stop.
        # bind_upstream hands this exact object to the upstream slave
        # protocol so a node with an upstream keeps ONE flood cache, not one
        # per protocol object.
        self._seen_flood_ids: FloodIdCache = FloodIdCache()
        # Floods this listener half has already decided how to answer.
        # Private to this half, unlike ``_seen_flood_ids`` above: see
        # ``handle_ping_message`` for why the node needs both records.
        self._answered_floods: FloodIdCache = FloodIdCache()
        # Floods this node has already FORWARDED, kept apart from the floods
        # it has already ANSWERED above. See ``_already_forwarded_flood``.
        self._forwarded_flood_cache = FloodIdCache()
        self._pending_cascades: dict = {}  # query_id -> CascadeCollector
        # guards lookup/creation of _pending_cascades entries: _route_query_response
        # runs both on the tornado thread (direct clients) and on the upstream
        # slave thread (cascade/query relayed from a master), so two threads can
        # race to create the same query_id's collector without this.
        self._cascades_lock = threading.Lock()
        self._last_seen_updates: dict = {}  # client.key -> last persisted timestamp
        self.last_seen_update_interval = _non_negative_float(
            get_server_config().get("last_seen_update_interval", 0),
            0.0,
        )
        self.ping_flood_interval = _non_negative_float(
            get_server_config().get("ping_flood_interval", 30),
            30.0,
        )
        self.agent_protocol.hm_protocol = self
        if not self.binary_data_protocol:
            # just logs received messages
            self.binary_data_protocol = BinaryDataHandlerProtocol(hm_protocol=self,
                                                                  agent_protocol=self.agent_protocol)
        else:
            self.binary_data_protocol.hm_protocol = self
        transformer_cfg = get_server_config()
        if self.utterance_transformers is None:
            self.utterance_transformers = UtteranceTransformersService(
                config=transformer_cfg.get("utterance_transformers") or {})
        if self.metadata_transformers is None:
            self.metadata_transformers = MetadataTransformersService(
                config=transformer_cfg.get("metadata_transformers") or {})
        if self.dialog_transformers is None:
            self.dialog_transformers = DialogTransformersService(
                config=transformer_cfg.get("dialog_transformers") or {})
        if self.policy_chain is None:
            from hivemind_core.policy import DenyAllPolicy
            cfg = get_server_config()
            try:
                self.policy_chain = PolicyChain.from_config(cfg, hm_protocol=self)
            except Exception:
                LOG.exception(
                    "failed to build policy chain; installing DenyAllPolicy "
                    "fallback \u2014 every admission will be rejected until "
                    "configuration is fixed"
                )
                self.policy_chain = PolicyChain(
                    policies=[DenyAllPolicy(hm_protocol=self)],
                )
        # every chain is normalized, including one handed to the constructor
        # by an embedder \u2014 the builtin gates are not opt-out
        self.policy_chain = self._with_builtin_policies(self.policy_chain)

    @property
    def trusted_pubkeys(self) -> dict:
        """TOFU pin store for INTERCOM origin authentication (CRYPTO-1 §5).

        Maps a client's access key to the PEM public key first seen for it.
        Lazily created so the field default can be ``None`` — a class
        attribute a bypass-built instance still sees.
        """
        if self._trusted_pubkeys is None:
            self._trusted_pubkeys = {}
        return self._trusted_pubkeys

    @trusted_pubkeys.setter
    def trusted_pubkeys(self, value: dict) -> None:
        self._trusted_pubkeys = value

    @property
    def _forwarded_flood_ids(self) -> FloodIdCache:
        """Floods this node has already forwarded, kept apart from the floods
        it has already answered. See ``_already_forwarded_flood``.

        Lazily created for the same reason as the other caches: the field
        default has to be ``None`` so a bypass-constructed instance sees it.
        """
        if self._forwarded_flood_cache is None:
            self._forwarded_flood_cache = FloodIdCache()
        return self._forwarded_flood_cache

    @_forwarded_flood_ids.setter
    def _forwarded_flood_ids(self, value: FloodIdCache) -> None:
        self._forwarded_flood_cache = value

    @property
    def _pending_cascades_lock(self) -> threading.Lock:
        """Guards lookup/creation of ``_pending_cascades`` entries.

        ``_route_query_response`` runs both on the tornado thread (direct
        clients) and on the upstream slave thread (a cascade or query relayed
        from a master), so two threads can race to create the same query_id's
        collector without this.

        __post_init__ builds the lock eagerly, so a normally-constructed node
        never reaches the lazy branch; that branch exists for fixtures built
        with ``object.__new__``, which are single-threaded.
        """
        if self._cascades_lock is None:
            self._cascades_lock = threading.Lock()
        return self._cascades_lock

    @property
    def _outstanding_queries(self) -> dict:
        """Participation-binding store (MSG-1 §5.2): query_id -> (return_peer,
        monotonic insert time). ``return_peer`` is the SERVER-OBSERVED peer of
        the connection the request arrived on — the only address authorized to
        receive the answer, never the client-claimed ``originator_peer``.
        Lazily built so a fixture constructed with ``object.__new__`` finds it
        instead of raising AttributeError."""
        if self._outstanding_queries_store is None:
            self._outstanding_queries_store = {}
        return self._outstanding_queries_store

    @property
    def _outstanding_queries_lock(self) -> threading.Lock:
        """Guards the outstanding-query store. ``_route_query_response`` runs on
        both the tornado thread and the upstream slave thread, so record/check/
        evict must be atomic (same reasoning as ``_pending_cascades_lock``)."""
        if self._outstanding_query_lock is None:
            self._outstanding_query_lock = threading.Lock()
        return self._outstanding_query_lock

    def _record_outstanding_query(self, query_id: str,
                                  return_peer: str) -> None:
        """Bind ``query_id`` to the connection it arrived on so the matching
        answer can only be routed back that way (MSG-1 §5.2). FIRST-WRITER-WINS:
        a query_id already bound is never rebound, so an attacker cannot steal a
        live query's return path by replaying its id. Bounded by a hard cap
        alongside the TTL eviction in ``_outstanding_return_path``; at the cap,
        the inserting peer's own oldest entry is evicted first, so a peer
        flooding distinct query_ids can only ever displace its own prior
        entries and can never starve other peers' outstanding queries."""
        now = time.monotonic()
        with self._outstanding_queries_lock:
            store = self._outstanding_queries
            if query_id in store:
                return
            while len(store) >= OUTSTANDING_QUERY_MAX:
                own = next((q for q, (p, _) in store.items()
                            if p == return_peer), None)
                store.pop(own if own is not None else next(iter(store)))
            store[query_id] = (return_peer, now)

    def _outstanding_return_path(self, query_id: str) -> Optional[str]:
        """The server-observed return peer this node recorded for ``query_id``,
        or None if it saw no request (forged, or evicted past
        ``OUTSTANDING_QUERY_TTL``). An answer is only ever delivered to this
        exact peer — a client-supplied originator_peer or route may select a
        candidate, but this authorizes the send."""
        now = time.monotonic()
        with self._outstanding_queries_lock:
            store = self._outstanding_queries
            for qid in [q for q, (_, ts) in store.items()
                        if now - ts > OUTSTANDING_QUERY_TTL]:
                store.pop(qid, None)
            entry = store.get(query_id)
            return entry[0] if entry else None

    @property
    def _seen_flood_ids(self) -> FloodIdCache:
        """Already-answered PING floods (MSG-1 §4), created lazily so the
        ``_flood_id_cache`` dataclass field can default to ``None`` — a class
        attribute a bypass-constructed instance still sees — without every
        node sharing one cache. See ``bind_upstream`` for why one node's two
        halves must share this same instance.
        """
        if self._flood_id_cache is None:
            self._flood_id_cache = FloodIdCache()
        return self._flood_id_cache

    @_seen_flood_ids.setter
    def _seen_flood_ids(self, value: FloodIdCache) -> None:
        self._flood_id_cache = value

    @property
    def identity_rsa_key(self) -> RSA.RsaKey:
        """The node's RSA identity key, imported from disk at most once.

        Every HiveMindClientConnection shares this same immutable key object
        instead of each re-reading and re-validating the PEM file itself —
        PyCryptodome's validation of a 2048-bit key measured 35-58ms, and it
        used to run inline on the IOLoop thread serving every connected
        client. Only this key is shared; each connection still gets its own
        fresh HandShake instance (see HiveMindClientConnection.__post_init__)
        because target_key/secret are per-peer session state that must never
        leak between connections. HandShake's own load-or-generate-if-missing
        logic is reused as-is; we keep only the resulting key object, never
        the bootstrap HandShake instance itself.
        """
        if self._identity_rsa_key is None:
            self._identity_rsa_key = HandShake(self.identity.private_key).private_key
        return self._identity_rsa_key

    # how many distinct passwords keep a derived PSK in memory at once
    NOISE_PSK_CACHE_SIZE = 256

    def noise_psk(self, password: Union[str, bytes]) -> bytes:
        """The Noise pre-shared key for ``password``, derived at most once.

        derive_psk runs argon2id (time_cost=3, 64 MiB) and measured
        152-333ms per call on the single IOLoop thread that serves every
        connected client. It is cacheable because its salt is
        SHA-256(node_id): the result depends only on the password and this
        node's id, both constant for the life of the node, so the same pair
        always yields the same key.

        Keyed on the password (and this node's id) rather than on the node
        id alone: Client rows carry their own password, so two clients may
        legitimately present different ones, and handing a client another
        client's PSK would silently break its handshake.
        """
        if isinstance(password, str):
            password = password.encode("utf-8")
        key = (password, self._node_id)
        psk = self._noise_psks.get(key)
        if psk is None:
            psk = derive_psk(password, node_id=self._node_id)
            self._noise_psks[key] = psk
            while len(self._noise_psks) > self.NOISE_PSK_CACHE_SIZE:
                self._noise_psks.popitem(last=False)
        else:
            self._noise_psks.move_to_end(key)
        return psk

    def _with_builtin_policies(self, chain: PolicyChain) -> PolicyChain:
        """Return ``chain`` with the non-removable builtin policies first.

        MessageTypeACLPolicy is the canonical ``allowed_types`` whitelist
        enforcement; DefaultSessionPolicy protects the reserved "default"
        session. Both are prepended to whatever chain we were given,
        deduping an explicitly listed copy so the operator cannot reorder
        or drop them. Always mandatory \u2014 their ``_optional`` entries are
        False, so an exception in a gate fails the chain closed.
        """
        from hivemind_core.policy import (DefaultSessionPolicy,
                                          MessageTypeACLPolicy)
        builtins = (MessageTypeACLPolicy, DefaultSessionPolicy)
        policies: List[PolicyPlugin] = []
        optional: List[bool] = []
        for i, p in enumerate(chain.policies):
            if isinstance(p, builtins):
                continue
            policies.append(p)
            optional.append(
                chain._optional[i] if i < len(chain._optional) else False
            )
        mandatory = [MessageTypeACLPolicy(hm_protocol=self),
                     DefaultSessionPolicy(hm_protocol=self)]
        return PolicyChain(
            policies=[*mandatory, *policies],
            _optional=[*[False] * len(mandatory), *optional],
            on_verdict=chain.on_verdict,
        )

    def get_bus(self, client: HiveMindClientConnection) -> Union[FakeBus, MessageBusClient]:
        # The agent decides which bus a client's messages land on. Default
        # agents return their single shared bus; a multiplexing agent (one
        # isolated brain per access key) returns a per-client bus, so per-key
        # routing on the inject path stays transparent here.
        return self.agent_protocol.get_bus(client)

    def _emit_lifecycle(self, client: HiveMindClientConnection,
                        message: Message) -> None:
        """Emit a connect/disconnect/error notification on the agent bus.

        These are notifications about the connection, not client traffic. An
        unreachable agent bus must not abort the handler that reports them:
        the connection still has to be accepted, cleaned up or rejected, and
        the peer has nothing to act on. So log and continue.
        """
        try:
            self.get_bus(client).emit(message)
        except ConnectionError as e:
            LOG.error(f"can not emit '{message.msg_type}' for {client.peer}, "
                      f"the agent bus is unreachable: {e}")

    def handle_new_client(self, client: HiveMindClientConnection):
        # "default" is the reserved device-local session: every OVOS message
        # carrying it writes into the orchestrator's own session store
        # (OVOS-SESSION-2 §5). A connection is not allowed to be born in it —
        # hivemind-websocket-protocol mints one that way as a placeholder, and
        # HELLO is not mandatory, so without this the placeholder can reach the
        # OVOS bus untouched (HIVEMIND-BRIDGE-1 §4.1). Admins that really want
        # the reserved session still get it by asking for it in HELLO.
        if client.sess.session_id == "default":
            client.sess = Session()
            LOG.debug(f"moved new connection off the reserved 'default' "
                      f"session to {client.sess.session_id}")

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

        self._emit_lifecycle(client, message)

        crypto_min = (
            ProtocolVersion.ONE
            if client.crypto_key is None and self.require_crypto
            else ProtocolVersion.ZERO
        )
        # The advertised minimum is the stricter of the configured floor and
        # the crypto-derived minimum.
        cfg_min = _configured_min_protocol_version()
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
            client.disconnect(1008, "server requires a protocol version this connection cannot offer")
            return

        hello_payload = {
            "pubkey": client.handshake.pubkey,
            # allows any node to verify messages are signed with this
            "peer": client.peer,  # this identifies the connected client in ovos message.context
            "node_id": self._node_id
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
        update_interval = self.last_seen_update_interval
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

        self.clients.pop(client.peer, None)
        # snapshot: a reconnect on another thread can insert while we iterate
        if not any(conn.key == client.key for conn in list(self.clients.values())):
            self._last_seen_updates.pop(client.key, None)
            # trusted_pubkeys is keyed by api-key, not peer, so a reconnect
            # under the same key must keep its TOFU pin — only drop it once
            # no live connection uses this key AND the key itself is gone
            # from the db (revoked/replaced), never just because of a single
            # disconnect. This runs off the hot path (disconnect, not every
            # message), so the db lookup is cheap enough to afford here.
            if client.key in self.trusted_pubkeys:
                with self.db:
                    if self.db.get_client_by_api_key(client.key) is None:
                        self.trusted_pubkeys.pop(client.key, None)
        # a pending cascade is only ever consumed in _route_query_response,
        # which requires ``originator_peer in self.clients`` before touching
        # its collector (see the CASCADE branch above) — once the originator
        # itself has disconnected, no future message can reach that check, so
        # its collectors are dead and safe to purge now instead of waiting
        # for 256-entry cap churn to evict them.
        with self._pending_cascades_lock:
            for query_id in [qid for qid, c in self._pending_cascades.items()
                              if c.originator_peer == client.peer]:
                self._pending_cascades.pop(query_id, None)
        # participation-binding state whose return path is this connection is
        # dead once it has disconnected — no future answer can reach it — so
        # purge it now instead of waiting for TTL/cap reclaim (MSG-1 §5.2).
        with self._outstanding_queries_lock:
            for qid in [q for q, (peer, _) in self._outstanding_queries.items()
                        if peer == client.peer]:
                self._outstanding_queries.pop(qid, None)
        client.disconnect()
        context = {"source": client.peer}
        # The disconnect notification carries the same Layer-1 session the
        # bus saw for this connection: translated for non-admins, raw for
        # admins (mirrors _install_client_session). The reserved
        # device-local "default" is still never handed to the bus on behalf
        # of a non-admin — it becomes "nonce:default" — while the agent can
        # correlate this disconnect to the session it actually saw
        # (HIVEMIND-BRIDGE-1 §4/§4.1). This emit is outside the policy chain.
        context["session"] = client.sess.serialize()
        context["session"]["session_id"] = (client.sess.session_id if client.is_admin
                                             else client.layer1_session_id)
        message = Message("hive.client.disconnect", {"key": client.key}, context)
        self._emit_lifecycle(client, message)

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
        self._emit_lifecycle(client, message)

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
        self._emit_lifecycle(client, message)

    def handle_message(self, message: HiveMessage, client: HiveMindClientConnection):
        """
        message (HiveMessage): HiveMind message object

        Process message from client, decide what to do internally here
        """
        # BEFORE the debug log below: rendering a HiveMessage calls as_json,
        # which asserts the payload is a dict, so a frame with a payload of
        # ``7`` or ``[1, 2]`` crashes on the log line, not in a handler.
        if not self._payload_is_usable(message, client):
            return

        LOG.debug(f"message: {message}")

        # Refresh is_admin and the can_broadcast/can_propagate/can_escalate
        # grants from the DB once, here, so every privilege-gated decision
        # downstream of this dispatcher (the session NAT in
        # _install_client_session, the BROADCAST/ESCALATE/PROPAGATE gates in
        # handle_broadcast_message/handle_escalate_message/
        # handle_propagate_message, ...) sees a value no staler than
        # resolve_user's TTL, instead of the connect-time snapshot for the
        # life of the connection (HIVEMIND-BRIDGE-1 §4/§4.1). The disconnect
        # lifecycle emit runs on socket close, outside this dispatcher, and
        # keeps reading whatever these grants were last refreshed to here.
        db = getattr(self, "db", None)
        if db is not None:
            try:
                user = client.resolve_user(db)
            except Exception:
                LOG.exception("handle_message: failed to resolve user for privilege refresh")
            else:
                if user is not None:
                    client.is_admin = user.is_admin
                    client.can_broadcast = user.can_broadcast
                    client.can_propagate = user.can_propagate
                    client.can_escalate = user.can_escalate

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
        elif message.msg_type == HiveMessageType.RENDEZVOUS:
            self.handle_rendezvous_message(message, client)
        else:
            self.handle_unknown_message(message, client)

        self.update_last_seen(client)

    @staticmethod
    def _probe_payload(message: HiveMessage) -> None:
        """Do everything ``handle_message`` and its handlers will later do to
        the payload of ``message``, so a payload that cannot be reconstructed
        raises here instead of inside a handler. Raises whatever the
        reconstruction raises.

        Two things touch the payload of an incoming frame:

        * ``as_json`` — the ``LOG.debug`` at the top of ``handle_message``
          renders the message, and ``as_dict`` asserts the payload is a dict.
        * ``HiveMessage.payload`` — it REBUILDS the payload for the types that
          carry a nested envelope: a bus ``Message`` for ``BUS`` and
          ``SHARED_BUS`` (``payload["type"]``), a ``HiveMessage`` for the five
          wrapper types (``HiveMessage(**payload)``). Both raise on a payload
          of the wrong shape. Every other type returns the payload as stored
          and can never raise, so probing unconditionally is free for them —
          and it removes the audit that the first version of this guard got
          wrong.

        The walk down the chain is what makes the guard deep enough. A wrapper
        handler does not stop at ``message.payload``: it reads
        ``message.payload.payload`` (``handle_propagate_message``,
        ``handle_escalate_message``, ``_answer_query_locally``) and forwards
        ``message.payload`` on to the next node, which will read a level deeper
        again. So every level is rebuilt here, not one. The loop terminates
        because each step descends one level of an already-parsed JSON object,
        and json.loads has bounded the depth before this point.
        """
        if message.msg_type != HiveMessageType.BINARY:
            message.as_dict  # what LOG.debug/__str__ does
        node = message
        while True:
            payload = node.payload
            if not isinstance(payload, HiveMessage):
                return
            node = payload

    def _payload_is_usable(self, message: HiveMessage,
                           client: HiveMindClientConnection) -> bool:
        """Check the payload of ``message`` can be reconstructed, at every
        level, before anything dereferences it.

        A peer that sends a payload of the wrong shape — a bus ``Message`` dict
        where HIVEMIND-MSG-1 §4 requires a nested ``HiveMessage``, a nested
        envelope missing ``type``, a bare number — makes the reconstruction
        raise, and the exception would escape the message handler and take the
        connection down. The frame is the sender's bug, so refuse it with the
        ``hive.policy.denied`` reply used for every other refused message and
        keep the peer connected: it is misinformed, not misbehaving, and it
        needs the reply to learn that.
        """
        try:
            self._probe_payload(message)
        except Exception as e:
            LOG.warning(f"malformed '{message.msg_type}' from {client.peer}: "
                        f"payload can not be reconstructed "
                        f"({type(e).__name__}: {e})")
            self._send_denied(
                client, str(message.msg_type), MALFORMED_PAYLOAD,
                f"'{message.msg_type}' payload can not be reconstructed "
                f"(HIVEMIND-MSG-1 §4)", {})
            return False
        return True

    # HiveMind protocol messages -  from slave -> master
    def handle_rendezvous_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        """Serve a RENDEZVOUS request, when this node holds mail.

        A rendezvous node is an ordinary node with the optional
        hivemind-rendezvous package installed and ``rendezvous.enabled`` set;
        ``mailbox`` is then bound at startup. Every other node answers
        "not_a_rendezvous_node" rather than dropping the frame, so a peer can
        tell "no mail" from "wrong node" and fail over.

        The mailbox is addressed by ``client.key`` — the access key this
        connection authenticated with — and never by anything in the request.

        It deliberately is NOT addressed by ``client.pub_key`` or by
        ``trusted_pubkeys``. Both are populated from the HELLO payload with no
        proof of possession (see ``handle_hello_message``), and
        ``trusted_pubkeys`` is keyed by the *caller's own* access key, so any
        admitted client could name a victim's public key — which is public by
        design, it is the INTERCOM addressing key — and be handed that
        victim's mailbox. The access key is proven by the handshake itself,
        which is what makes it safe to own a mailbox.
        """
        if self.mailbox is None:
            client.send(self._name_the_mailbox(HiveMessage(
                HiveMessageType.RENDEZVOUS,
                payload={"status": "error", "reason": "not_a_rendezvous_node"})))
            return
        if not client.key:
            # No authenticated identity means no mailbox to serve. Falling
            # through would hand every such connection one shared mailbox.
            client.send(self._name_the_mailbox(HiveMessage(
                HiveMessageType.RENDEZVOUS,
                payload={"status": "error", "reason": "no_client_identity"})))
            return
        try:
            reply = self.mailbox.handle(message, client.key)
        except Exception:
            # The mailbox is an optional third-party component. An exception
            # here used to escape handle_message and take the connection down
            # with it, skipping update_last_seen on the way out.
            LOG.exception(f"rendezvous mailbox failed for {client.peer}")
            reply = HiveMessage(HiveMessageType.RENDEZVOUS,
                                payload={"status": "error",
                                         "reason": "mailbox_error"})
        client.send(self._name_the_mailbox(reply))

    def _name_the_mailbox(self, reply: HiveMessage) -> HiveMessage:
        """Say which node answered, so a dead drop can be identified.

        A mailbox belongs to the node holding it, and every node in a hive may
        hold one. Two peers that deposit and collect against different nodes
        each get a well-formed answer — ``{"status": "ok", "messages": []}``
        for the collector — and neither can tell it is reading a different
        dead drop from the one written to. The exchange fails as silence.

        Naming the node makes that visible without changing where mail lives:
        a depositor and a collector comparing ``mailbox_node`` can see whether
        they met, and a client that wants a particular dead drop can tell
        whether it reached it. This covers every RENDEZVOUS reply this node
        sends, including the two early "not a mailbox" / "no identity"
        answers below — a peer failing over needs to know which node just
        refused it as much as it needs to know which node served mail.

        Like ``_rewrap`` (HIVEMIND-NODE-1 §3.3), the reply is rebuilt with a
        naive ``HiveMessage(type, payload=payload)`` only if we also drop
        ``metadata``, ``target_site_id`` and ``target_pubkey`` — all three
        are constructor-only, so they must be carried explicitly or a
        third-party mailbox that set any of them (it is documented as an
        optional third-party component) loses them silently.

        ``mailbox_node`` is always present in the returned payload, even when
        this node has no identity yet — as ``None`` rather than a missing
        key. A consumer doing ``payload["mailbox_node"]`` must not have to
        guess whether absence means "this node has no identity" or "this
        code predates the field"; ``None`` says the former outright, and two
        ``None``s must never compare equal as "we met" (checked below). Once
        every node is guaranteed a public key (tracked in a separate PR),
        this is the value only a not-yet-provisioned node emits — it is the
        transitional case, not the steady state.

        If the mailbox already stamped its own ``mailbox_node``, this node's
        identity overwrites it rather than being merged in. The point of the
        field is to say which node *actually answered this connection*, which
        is always this node — a mailbox is documented as addressed by
        ``client.key`` on this node, never as a proxy fronting another node's
        drop, so its own claim about who it is on someone else's behalf isn't
        one we can trust. Preserving it would let a buggy or malicious
        mailbox spoof identity, defeating the reason the field exists.
        """
        payload = reply.payload
        if not isinstance(payload, dict):
            return reply
        payload = dict(payload)
        payload["mailbox_node"] = self._node_id or None
        return HiveMessage(
            HiveMessageType.RENDEZVOUS, payload=payload,
            metadata=reply.metadata,
            target_site_id=reply.target_site_id,
            target_pubkey=reply.target_public_key,
        )

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
        client.disconnect(1008, reason)

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
                    psk=self.noise_psk(client.pswd_handshake.password),
                    password=None,
                    node_id=self._node_id, prologue=prologue,
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
                client,
                "client Noise static key contradicts the pinned key. If this "
                "client was reinstalled or moved to new hardware, clear the "
                f"pin with 'hivemind-core reset-noise-pin {client.key}' and "
                "let it pair again; otherwise another node is answering for it")
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

        # enforce the operator-configured protocol floor (HIVEMIND-CRYPTO-1
        # §3.4 fail-closed floor semantics). The v3-capability check at HELLO
        # time (min_version > max_version) only rejects clients that *cannot*
        # reach the floor at all; it does not stop a v3-capable client
        # (password handshake present) from completing a legacy v1/v2
        # handshake instead of Noise, silently ignoring a raised floor. Noise
        # ("noise" in payload) is handled above and always satisfies any
        # floor, so only the legacy branches below need the check.
        cfg_min = _configured_min_protocol_version()
        if "pubkey" in message.payload and client.handshake is not None:
            attempted_version = ProtocolVersion.ONE
        elif client.pswd_handshake is not None and "envelope" in message.payload:
            attempted_version = ProtocolVersion.TWO
        else:
            attempted_version = None
        if attempted_version is not None and attempted_version < cfg_min:
            LOG.warning(
                f"rejecting {client.peer}: legacy handshake at protocol "
                f"v{int(attempted_version)} is below the configured minimum "
                f"v{int(cfg_min)}"
            )
            client.disconnect(1008, f"legacy handshake at protocol v{int(attempted_version)} "
                                     f"is below the configured minimum v{int(cfg_min)}")
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
                client.disconnect(1008, "invalid cipher/encoding negotiation")
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
                client.disconnect(1008, "password handshake verification failed")
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
            client.disconnect(1008, "invalid or unrecognized handshake")
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
            try:
                client.sess = Session.deserialize(payload["session"])
            except MalformedSession as e:
                LOG.warning(f"malformed HELLO session from {client.peer}: {e}")
                self._send_denied(
                    client, str(message.msg_type), MALFORMED_PAYLOAD,
                    f"HELLO 'session' can not be reconstructed "
                    f"(HIVEMIND-MSG-1 §4)", {})
                return
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
        # A non-admin client may declare "default" here (HIVEMIND-BRIDGE-1
        # §4/§4.1): _install_client_session stamps every inbound BUS message
        # with a per-connection Layer-1 session id ("<nonce>:<session_id>")
        # before the policy chain runs, so this remote "default" can never
        # reach the OVOS bus as the bare, device-local "default" session.

        # a client that HELLOs again with a different session_id leaves a
        # stale entry behind under its old peer id — drop it, or a later
        # connection collides with a peer that no longer exists.
        for peer, conn in list(self.clients.items()):
            if conn is client and peer != client.peer:
                self.clients.pop(peer)

        # HIVEMIND-BRIDGE-1 §3: every peer needs a distinct ``source``.
        # ``name`` comes from the access key and ``session_id`` comes from
        # this HELLO, so two connections that share an access key can ask
        # for the same peer string. The second one would evict the first
        # from ``self.clients`` and then receive its responses
        # (HIVEMIND-AGENT-1 §3). Give the newcomer a server-generated
        # suffix instead — BRIDGE-1 §3.1 allows exactly this.
        other = self.clients.get(client.peer)
        if other is not None and other is not client:
            client._peer_suffix = f"::{uuid.uuid4().hex[:8]}"
            LOG.warning(f"peer id collision on '{other.peer}'; the new "
                        f"connection is now known as '{client.peer}'")
        self.clients[client.peer] = client

    def handle_bus_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        """Forward a client's internal bus message to the agent bus.

        A bus payload never mutates ``client.sess``: that stays the
        connection's HELLO-established baseline and changes only on
        (re-)HELLO. Each message declares its own session;
        ``_install_client_session`` derives that message's Layer-1
        (orchestrator) session id and merges the payload's session contents
        over the baseline (HIVEMIND-BRIDGE-1 §4). The "default" session id is
        gated by ``OVOSAgentPolicy.review`` — a non-admin payload using it is
        denied and dropped, not forwarded.
        """
        try:
            payload = message.payload
        except (AttributeError, KeyError, TypeError, ValueError):
            LOG.warning("Ignoring BUS payload with invalid message/context shape")
            return

        if not isinstance(payload, Message) or not isinstance(payload.context, dict):
            LOG.warning("Ignoring BUS payload with invalid message/context shape")
            return

        # The per-message "session_id == 'default'" gate moved to
        # OVOSAgentPolicy.review (HiveMind-core#85). Non-admin clients
        # injecting a default-session payload get Verdict.deny(
        # "session_id_default_forbidden", ...) and the message is dropped
        # with a hive.policy.denied response — replacing the previous
        # severe `client.disconnect()` reaction. The HELLO-time check at
        # handle_hello_message stays as connection-establishment gate.
        #
        # A bus payload NEVER mutates ``client.sess``: that stays the
        # HELLO-established baseline for the connection and only changes on
        # (re-)HELLO (handle_hello_message). A single connection may
        # multiplex several declared sessions (a relay, or a per-call bridge
        # like baresip); each message declares its own session and
        # ``_install_client_session`` derives that message's Layer-1 identity
        # and merges its contents over the baseline (HIVEMIND-BRIDGE-1 §4).
        self.handle_inject_agent_msg(payload, client)

    def handle_broadcast_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        """
        message (HiveMessage): HiveMind message object
        """
        payload = self._unpack_message(message, client)

        # BROADCAST stays an admin privilege, and ``can_broadcast`` narrows it:
        # the DB column defaults to True, so an operator who revokes it on an
        # admin client stops that client's broadcasts, while ordinary clients
        # gain nothing from the default.
        if not (client.is_admin and client.can_broadcast):
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

        # broadcast message to other peers (NODE-1 §3.3: keep the envelope)
        fwd = self._rewrap(message, payload)
        # snapshot: disconnects/reconnects mutate self.clients from other threads
        plaintext = fwd.serialize()
        for conn in list(self.clients.values()):
            if conn.peer == client.peer:
                continue
            try:
                conn.send(fwd, plaintext)
            except Exception:
                LOG.exception(f"failed to forward to {conn.peer}")

    def _unpack_message(self, message: HiveMessage, client: HiveMindClientConnection):
        # propagate message to other peers
        pload = message.payload
        # keep info about which nodes this message has been to
        pload.replace_route(message.route)
        pload.update_source_peer(self._node_id)
        pload.remove_target_peer(client.peer)
        return pload

    def _rewrap(self, message: HiveMessage, payload: HiveMessage,
                metadata: Optional[dict] = None) -> HiveMessage:
        """Wrap an unpacked ``payload`` back into an outer envelope of the same
        type as ``message``.

        HIVEMIND-NODE-1 §3.3: a relay MUST preserve the envelope it relays.
        ``metadata``, ``target_site_id`` and ``target_pubkey`` are
        constructor-only on ``HiveMessage``, so a naive
        ``HiveMessage(type, payload=payload)`` silently drops them — and site
        targeting is read off the OUTER envelope, so a site-targeted message
        would stop being deliverable after one relay hop.
        """
        fwd = HiveMessage(
            message.msg_type, payload=payload,
            metadata=message.metadata if metadata is None else metadata,
            target_site_id=message.target_site_id,
            target_pubkey=message.target_public_key,
        )
        # MSG-1 §5: carry the accumulated route (incl. our self-hop) on the
        # outer envelope so the next node can detect a loop
        fwd.replace_route(payload.route)
        return fwd

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

    @staticmethod
    def _flood_peer(message: HiveMessage) -> str:
        """The ``peer`` a flood message announces, or ``""`` when it names none.

        A flood is not one message. Every node that answers builds its own PING
        carrying the same ``flood_id`` and its own ``peer``, so one flood id
        covers as many distinct announcements as there are answering nodes.
        """
        inner = message.payload
        if isinstance(inner, HiveMessage):
            inner = inner.payload
        return inner.get("peer", "") if isinstance(inner, dict) else ""

    @staticmethod
    def _flood_id(message: HiveMessage) -> str:
        """The ``flood_id`` a routing message carries, or ``""`` when it carries
        none.

        The id lives on the innermost payload mapping — a PROPAGATE wraps a PING
        whose payload is the plain mapping described in MSG-1 §4. Messages that
        are not floods (a PROPAGATE around a BUS ``Message``, a QUERY, ...) have
        no such mapping and yield ``""``, which every caller reads as "not a
        flood, no dedup applies".
        """
        inner = message.payload
        if isinstance(inner, HiveMessage):
            inner = inner.payload
        return inner.get("flood_id", "") if isinstance(inner, dict) else ""

    def _already_forwarded_flood(self, message: HiveMessage) -> bool:
        """HIVEMIND-MSG-1 §4 / NODE-1 §4: a node drops a flood whose ``flood_id``
        it has already seen. Returns True when this node has already forwarded
        this flood, and records the id otherwise.

        This is a **second, independent** gate on top of the §5 route-loop check.
        Route-loop suppression only stops a message that carries this node in its
        own ``route``; a responsive PING is built fresh by the answering node
        (empty ``route``, same ``flood_id``), so it looks brand new at every hop.
        Without this gate a master re-fans every one of the n responses to all
        n-1 other peers, and the mesh cost of one ping round grows as n(n-1)^2.

        The forwarded ids are tracked **separately** from
        :attr:`_seen_flood_ids`, which records the floods this node has already
        *answered*. Answering and forwarding are different decisions taken at
        different moments: ``handle_ping_message`` answers (and marks the flood
        answered) *before* the forwarding block below runs, so a shared set would
        make the node consider every flood already forwarded on first sight and
        the flood would never leave the node that received it.

        Deduplication is deliberately per-node and not per-peer: once a flood has
        crossed this node in any direction it has reached everything this node
        can reach, so a second copy arriving from another peer adds nothing.
        """
        flood_id = self._flood_id(message)
        if not flood_id:
            return False
        # Keyed on (flood_id, peer), not flood_id alone.
        #
        # One flood carries one announcement per answering node. Collapsing
        # them by flood_id makes a node forward whichever arrives first and
        # silently drop the rest, so a satellite below a relay never learns
        # the nodes above it — and not only for someone else's flood: when it
        # floods itself, every answer comes back wrapped with ITS flood id, so
        # the relay forwards one of them and the originator's own map comes
        # back incomplete. A topology probe that quietly reports a wrong
        # topology is worse than an expensive one.
        #
        # The duplication this gate exists for is still removed: the same
        # node's announcement crossing this node twice is what cost
        # n(n-1)^2, and that is still dropped. Mesh-wide answer volume is
        # bounded by ping_flood_interval, which is the knob for cost.
        #
        # The mapper already keys its own novelty check the same way, so this
        # brings the gate in line with how the rest of the node models a
        # flood.
        flood_id = f"{flood_id}\x00{self._flood_peer(message)}"
        # FloodIdCache.check() records the id and reports whether it was
        # already there, so the test and the insert cannot race. Sized from
        # the client count like the answer caches: every connected peer can
        # start a flood of its own, and each eviction of a live flood_id buys
        # a duplicate fan-out.
        return self._forwarded_flood_ids.check(
            flood_id, max_size=max(1000, len(self.clients) * 100))

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

        # MSG-1 §4: a flood crosses each node once. Local delivery above already
        # ran (the mapper sees every PING, answered or not); only the fan-out is
        # dropped for a flood this node has forwarded before.
        if self._already_forwarded_flood(message):
            LOG.debug("not re-forwarding PROPAGATE for already seen "
                      f"flood_id={self._flood_id(message)} (MSG-1 §4)")
            return

        # propagate message to other peers (NODE-1 §3.3: keep the envelope, so a
        # peer receives a PROPAGATE it can fan out again instead of a bare BUS)
        fwd = self._rewrap(message, payload)
        plaintext = fwd.serialize()
        for conn in list(self.clients.values()):
            if conn.peer == client.peer:
                continue
            try:
                conn.send(fwd, plaintext)
            except Exception:
                LOG.exception(f"failed to forward to {conn.peer}")

        # forward upstream to the master this node relays to (no-op at top level)
        self.propagate_to_master(fwd)

    def handle_ping_message(
            self, message: HiveMessage, client: HiveMindClientConnection
    ):
        """Handle an inner PING message received inside a PROPAGATE wrapper.

        Feeds the PING into the local ``HiveMapper``, emits ``hive.ping.received``
        on the agent bus for each newly observed peer, then — if this
        ``flood_id`` has not been seen before — answers with this node's own
        PING carrying the same ``flood_id``. That answer fans out to all peers
        and upstream at most once per ``ping_flood_interval`` seconds; inside
        the window it goes to the asking peer alone.

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

        # The mapper is the topology view, so it must see arrivals the dedup
        # gate below drops: each one names a different peer and carries a
        # different route. It keeps its own (flood_id, peer) index and answers
        # False for an arrival it has already folded in.
        new_to_map = self.hive_mapper.on_ping(message, received_at=time.time())

        # Surface observed PINGs on the agent bus (discovery/telemetry), gated
        # on the mapper's novelty answer so one send goes out per (flood_id,
        # peer) instead of one per arrival. A peer that reaches us over several
        # mesh paths is the same observation each time, and repeating it puts
        # the mesh's fan-out factor onto the agent bus. Still ahead of the
        # dedup gate: a flood we already answered keeps carrying peers we have
        # never seen, and those are the discoveries.
        if new_to_map:
            # Telemetry on the way past, not a step in answering. A flood is
            # asked precisely when something is wrong, and an unreachable OVOS
            # bus is one of the things being diagnosed — letting that failure
            # out of here silenced the node's answer and made a hive that was
            # merely missing its agent look unreachable. Same reasoning as
            # _emit_lifecycle: log and carry on.
            try:
                self.agent_protocol.bus.emit(Message("hive.ping.received", {
                    "flood_id": flood_id,
                    "peer": ping_payload.get("peer"),
                    "site_id": ping_payload.get("site_id"),
                    "timestamp": ping_payload.get("timestamp"),
                }))
            except Exception as e:
                LOG.error(f"can not publish 'hive.ping.received' for "
                          f"{ping_payload.get('peer')}, the agent bus is "
                          f"unreachable: {e}")

        # Flood-loop prevention (MSG-1 §4): answer a flood at most once.
        #
        # "Once" is once per node, not once per direction. NODE-1 §4 says a
        # responsive PING is itself PROPAGATE-wrapped and fans out across the
        # mesh, so the node's single answer must reach downstream clients AND
        # upstream. Suppressing this whole half because the slave half already
        # answered upstream leaves the relay missing from the hive map of the
        # very clients attached to it.
        #
        # So the node keeps two records:
        #   * ``_seen_flood_ids`` — shared with the upstream slave protocol
        #     (see bind_upstream). It says "a half of this node already sent
        #     the answer upstream", so the master never sees two.
        #   * ``_answered_floods`` — private to this half. It says "this half
        #     already decided how to answer this flood", so repeat arrivals
        #     from several clients neither re-flood nor re-answer.
        #
        # Both caches grow with the client count, because every connected peer
        # can start a flood of its own. A fixed 1000 thrashes on a large mesh,
        # and each eviction of a live flood_id buys a duplicate flood.
        flood_cache_size = max(1000, len(self.clients) * 100)
        if not flood_id or self._answered_floods.check(flood_id,
                                                       max_size=flood_cache_size):
            return

        # Build our own responsive PING with the same flood_id.
        # ``peer`` is the map key; ``public_key`` is the node's stable
        # identity, and the slave protocol's responsive PING carries it too.
        # Sending both keeps one node from being mapped as two when a flood
        # is answered by whichever half of the node saw it first.
        own_ping_payload = {
            "flood_id": flood_id,
            "peer": self._node_id,
            "site_id": self.identity.site_id,
            "timestamp": time.time(),
            "public_key": self.identity.public_key,
        }
        own_ping_inner = HiveMessage(HiveMessageType.PING, own_ping_payload)
        own_ping_outer = HiveMessage(HiveMessageType.PROPAGATE, payload=own_ping_inner)

        # Every satellite floods on its own schedule, and each flood costs this
        # node one send per peer, so unthrottled the node's work per round grows
        # with the square of the mesh size — the point where a large site stops
        # completing rounds at all. At most one mesh-wide fan-out per
        # ping_flood_interval seconds; the peers that ask inside that window are
        # answered directly instead, one send each.
        #
        # This check comes BEFORE the ``_seen_flood_ids`` claim below, and the
        # order is load-bearing. That claim means "this node owes the master an
        # answer for this flood, and the other half must not send a second
        # one". Claiming it and then returning here would leave the answer owed
        # by nobody: the throttled half never sends it, and the slave half is
        # suppressed because the claim is shared. The master would silently
        # stop seeing this node. Taking the throttle first leaves the claim
        # untouched, so nothing is promised that is not then sent.
        #
        # The accepted cost is that a throttled flood carries no answer of ours
        # upstream at all. That is the point of the throttle, and the next
        # unthrottled flood re-announces this node.
        now = time.time()
        if now - self._last_ping_flood < self.ping_flood_interval:
            LOG.debug(f"answering PING flood_id={flood_id} to {client.peer} only; "
                      f"next mesh-wide flood in "
                      f"{self.ping_flood_interval - (now - self._last_ping_flood):.1f}s")
            client.send(own_ping_outer)
            return
        self._last_ping_flood = now

        # Past the throttle, so this really is a mesh-wide answer. Atomic
        # across both halves: whoever wins owes upstream the answer, the loser
        # already has one in flight from its other half.
        owes_upstream = not self._seen_flood_ids.check(flood_id,
                                                       max_size=flood_cache_size)

        LOG.debug(f"Sending responsive PING for flood_id={flood_id}")

        # NODE-1 §4: a PING fans out across the whole mesh — downstream peers
        # and upstream alike, so a master learns of nodes below a relay and a
        # satellite still sees the relay it is attached to.
        #
        # The envelope is serialized once and handed to every peer: the
        # plaintext is identical for all of them, only the per-connection
        # encryption differs. One peer failing to send must not cost the
        # others their PING, so each send is isolated.
        plaintext = own_ping_outer.serialize()
        for conn in list(self.clients.values()):
            try:
                conn.send(own_ping_outer, plaintext)
            except Exception:
                LOG.exception(f"failed to send PING to {conn.peer}")
        if owes_upstream:
            self.propagate_to_master(own_ping_outer)

    def bind_upstream(self, slave) -> None:
        """Bind a ``HiveMindSlaveProtocol`` as this node's upstream connection,
        turning it into a relay: BROADCAST/PROPAGATE from the upstream master
        are fanned out to downstream clients, and downstream PROPAGATE/ESCALATE
        are forwarded upstream. ``slave`` must already be bound to a bus.

        This is also where the node stops being two PING participants and
        becomes one. Both protocol objects handle PING independently, so
        with a flood cache each they both answer the same flood — under two
        different identities, because the slave answers as its connection
        peer and the listener as its public key. The flood's originator then
        records two nodes where there is one. Sharing ``_seen_flood_ids``
        makes the first half to see a ``flood_id`` claim the upstream answer
        and suppress the other, which is what HIVEMIND-NODE-1 §4 requires:
        the **node** takes part exactly once. A node with no upstream never
        gets here and still answers exactly once, through the listener.

        Sharing the cache settles the *upstream* answer only. The downstream
        fan-out stays with the listener either way — see
        ``handle_ping_message`` — because a relay must appear in the hive map
        of its own clients, not only in its master's.
        """
        self._upstream_hm = slave.hm
        slave.bind_flood_cache(self._seen_flood_ids)
        slave.hm.on(HiveMessageType.BROADCAST, self.broadcast_from_master)
        slave.hm.on(HiveMessageType.PROPAGATE, self.propagate_from_master)
        slave.hm.on(HiveMessageType.QUERY, self.query_from_master)
        slave.hm.on(HiveMessageType.CASCADE, self.cascade_from_master)

    def _relay_downstream(self, message: HiveMessage) -> None:
        """Fan a routing message received from the upstream master out to every
        downstream client, with NODE-1 §3.4 loop prevention: a message whose
        route already names this node is not relayed again, and MSG-1 §4 flood
        dedup: a flood this node already relayed is not relayed again."""
        if self._is_routing_loop(message):
            LOG.debug(f"not relaying {message.msg_type} already routed through "
                      f"this node {self._node_id} (NODE-1 §3.4); "
                      f"route={message.route}")
            return
        if self._already_forwarded_flood(message):
            LOG.debug(f"not relaying {message.msg_type} for already seen "
                      f"flood_id={self._flood_id(message)} (MSG-1 §4)")
            return
        self._append_self_hop(message)
        plaintext = message.serialize()
        for conn in list(self.clients.values()):
            try:
                conn.send(message, plaintext)
            except Exception:
                LOG.exception(f"failed to relay to {conn.peer}")

    def broadcast_from_master(self, message: HiveMessage) -> None:
        """Fan a BROADCAST received from the upstream master out to all
        downstream clients.

        No loop machinery here: NODE-1 §4 makes BROADCAST a single hop to the
        directly connected downstream nodes, never re-broadcast by recipients.
        It only ever travels upstream-to-downstream, so it cannot cycle.
        """
        plaintext = message.serialize()
        for conn in list(self.clients.values()):
            try:
                conn.send(message, plaintext)
            except Exception:
                LOG.exception(f"failed to broadcast to {conn.peer}")

    def propagate_from_master(self, message: HiveMessage) -> None:
        """Fan a PROPAGATE received from the upstream master out to all
        downstream clients."""
        self._relay_downstream(message)

    def escalate_to_master(self, message: HiveMessage) -> None:
        """Forward an ESCALATE envelope upstream. No-op when this node is the
        top-level master (nothing bound via :meth:`bind_upstream`)."""
        if self._upstream_hm is None:
            return
        self._upstream_hm.emit(message)

    def propagate_to_master(self, message: HiveMessage) -> None:
        """Forward a PROPAGATE envelope upstream. No-op when this node is the
        top-level master (nothing bound via :meth:`bind_upstream`)."""
        if self._upstream_hm is None:
            return
        self._upstream_hm.emit(message)

    def query_from_master(self, message: HiveMessage) -> None:
        """Relay a QUERY received from the upstream master.

        A *response* belongs to the one peer that asked (NODE-1 §5.2), so it
        walks the return path; only requests fan out downstream.
        """
        if (message.metadata or {}).get("is_response"):
            self._route_query_response(message, None)
            return
        # A master-originated request has no downstream return path recorded on
        # this node (the request came FROM upstream, not from a downstream peer
        # this node admitted), so no participation state is bound here; the
        # matching response has nowhere authorized to go and drops at
        # _route_query_response, unchanged from before this binding existed.
        self._relay_downstream(message)

    def query_to_master(self, message: HiveMessage) -> None:
        """Forward a QUERY envelope upstream. No-op at the top-level master."""
        if self._upstream_hm is None:
            return
        self._upstream_hm.emit(message)

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
        lang = (admitted.data.get("lang") or admitted.context.get("lang")
                or self.default_lang)
        if self.utterance_transformers.plugins and utts:
            utts, context = self.utterance_transformers.transform(
                utts, dict(admitted.context))
            if context.get("canceled"):
                LOG.info(f"QUERY utterance from {client.peer} canceled by "
                         f"{context.get('cancel_by')}: {context.get('cancel_reason')}")
                return False
        utterance = utts[0] if utts else ""
        if not utterance:
            return False
        answered = False
        try:
            for chunk in self.agent_protocol.answer_query(utterance, lang, client=client):
                if chunk is None:
                    break
                answered = True
                if self.dialog_transformers.plugins:
                    chunk, _ = self.dialog_transformers.transform(
                        chunk, {"lang": lang})
                resp = Message("speak", {"utterance": chunk, "lang": lang},
                               {"query_id": query_id})
                send_fn(self._build_query_response(
                    msg_type, resp, query_id, originator_peer, self._node_id,
                    route=route))
        except NotImplementedError:
            return False  # agent has no NL backend -> escalate
        if answered:
            send_fn(self._build_query_response(
                msg_type, Message(QUERY_STREAM_END, {}), query_id,
                originator_peer, self._node_id, route=route))
        return answered

    def _route_query_response(self, message: HiveMessage,
                              client: Optional[HiveMindClientConnection]):
        """Route a QUERY response downstream toward its originator: the direct
        client if it is connected here, else the downstream hop the request
        arrived on (from the recorded route). A response that resolves to
        neither is dropped — see the end of this method.

        ``client`` is the connection the response arrived on; it is never a
        return path for its own response. It is None when the response came
        from upstream.
        """
        sender = client.peer if client else None
        metadata = message.metadata or {}
        originator_peer = metadata.get("originator_peer", "")
        query_id = metadata.get("query_id", "")
        # Participation binding (MSG-1 §5.2): route an answer only to the
        # SERVER-OBSERVED connection the matching request arrived on. Both the
        # client-supplied ``originator_peer`` and the client-supplied route may
        # only SELECT a candidate connection below — the recorded return path
        # AUTHORIZES the actual send. This closes two forgery vectors an
        # existence-only check missed: (1) self-record — an attacker sends a
        # request claiming a victim's originator_peer, then an answer for the
        # same id; and (2) crafted-route — an attacker plants a victim hop in
        # the route. In both the chosen candidate's peer is the attacker's, not
        # the recorded arriving connection, so the send is refused.
        return_peer = self._outstanding_return_path(query_id)
        if return_peer is None:
            LOG.warning(
                "dropping unbacked %s response (participation binding, "
                "MSG-1 §5.2): no request seen for query_id=%s "
                "originator_peer=%s" % (message.msg_type, query_id,
                                        originator_peer))
            return
        # One lookup serves both the CASCADE gate below and the default route
        # at the end. An "in" check followed by an index would KeyError if the
        # originator disconnected between the two, and that KeyError travels up
        # to the websocket handler and drops the *responder's* connection.
        originator_conn = self.clients.get(originator_peer)
        # CASCADE disambiguation: collect responses for a select callback at
        # the originating node, letting it pick a winner progressively. Only
        # when THIS node is the genuine originator — the direct originator
        # connection is the recorded return path — so a forged originator_peer
        # can not trigger the collector (and a relay does not mis-collect).
        if (message.msg_type == HiveMessageType.CASCADE
                and self.cascade_select_callback is not None
                and originator_conn is not None
                and originator_conn.peer == return_peer):
            query_id = metadata.get("query_id", "")
            # _route_query_response runs both on the tornado thread (direct
            # clients) and on the upstream slave thread (relayed cascades), so
            # the lookup/creation of a query_id's collector must be atomic:
            # otherwise two threads can each create one, and whichever loses
            # the final assignment has its responses silently discarded.
            with self._pending_cascades_lock:
                collector = self._pending_cascades.get(query_id)
                if collector is None:
                    # AGENT-1 §4.3: bound the collector map. It counts concurrent
                    # queries — a collector holds one entry per responder, so the
                    # per-query state is bounded by the mesh, not by chunk count.
                    while len(self._pending_cascades) >= 256:
                        self._pending_cascades.pop(next(iter(self._pending_cascades)))
                    collector = CascadeCollector(
                        query_id=query_id, originator_peer=originator_peer)
                    self._pending_cascades[query_id] = collector
            collector.add_response(message)
            try:
                bus = self.get_bus(originator_conn)
            except ConnectionError as e:
                # keep the collector: the responses stay queued and the next
                # one retries once the agent bus is back
                LOG.error(f"can not run the cascade select callback for "
                          f"query_id={query_id}, the agent bus is "
                          f"unreachable: {e}")
                return
            try:
                selected = self.cascade_select_callback(query_id, collector.responses)
                if selected is not None:
                    bus.emit(selected)
                    with self._pending_cascades_lock:
                        self._pending_cascades.pop(query_id, None)
            except Exception:
                LOG.exception(f"cascade_select_callback error for query_id={query_id}")
            return
        # Default routing: forward toward the originator, but only if the
        # candidate connection IS the recorded return path. A client-claimed
        # originator_peer that resolves to some other live connection is a
        # forged target and must not receive the answer.
        conn = originator_conn
        if conn is not None and conn.peer == return_peer:
            conn.send(message)
            return
        # route-aware return: the downstream hop on the path back to the
        # originator (from the request's recorded route). Same authorization —
        # a client-planted victim hop never equals the recorded return path.
        for hop in reversed(message.route or []):
            src = hop.get("source")
            if not src or src == sender or src != return_peer:
                continue
            conn = self.clients.get(src)
            if conn is not None:
                conn.send(message)
                return
        # no authorized return path: the recorded arriving connection is gone,
        # or the claimed target/route names some other peer. Delivering anywhere
        # else hands one peer's answer to another (NODE-1 §5.2, AGENT-1 §3.2),
        # so drop it.
        LOG.warning(f"dropping {message.msg_type} response with no authorized "
                    f"return path: query_id={metadata.get('query_id', '')} "
                    f"originator_peer={originator_peer} return_peer={return_peer}")

    def handle_query_message(self, message: HiveMessage,
                             client: HiveMindClientConnection):
        """QUERY — like ESCALATE but expects a response. Request: try the local
        agent; if answered, reply downstream; else escalate upstream (or return
        a no-answer error at the top). Response: route downstream to originator.
        """
        LOG.info(f"Received QUERY from: {client.peer}")
        metadata = message.metadata or {}
        if not client.can_escalate:
            # HIVEMIND-AGENT-1 §3.2: a client without escalate permission may
            # not author a QUERY, and that includes forging a fake "response"
            # to smuggle an arbitrary payload to an arbitrary peer by name
            # (metadata.originator_peer) — the response branch below trusts
            # that field with no other proof of participation, so it must be
            # gated by the same permission as the request branch, not skipped
            # ahead of it.
            LOG.warning("Received QUERY from client without escalate permission")
            if self.illegal_callback:
                self.illegal_callback(self._unpack_message(message, client))
            client.disconnect()
            return

        if metadata.get("is_response", False):
            self._route_query_response(message, client)
            return

        payload = self._unpack_message(message, client)
        query_id = metadata.get("query_id", str(uuid.uuid4()))
        originator_peer = metadata.get("originator_peer", client.peer)
        # participation binding (MSG-1 §5.2): bind this query to the connection
        # it arrived on (client.peer, the server-observed return path — NOT the
        # client-claimed originator_peer), before any answer routes. The answer
        # is only ever delivered back to this exact connection.
        self._record_outstanding_query(query_id, client.peer)
        try:
            bus = self.get_bus(client)
        except ConnectionError as e:
            # without the agent bus this node can not answer the query at
            # all; tell the originator instead of dropping it in silence
            self._send_backend_unavailable(client, message, e)
            return
        bus.emit(Message("hive.query.received",
                         {"query_id": query_id, "originator_peer": originator_peer},
                         {"source": client.peer}))

        if self._answer_query_locally(message, client, query_id, originator_peer,
                                      HiveMessageType.QUERY, message.route,
                                      client.send):
            return

        if self._upstream_hm is not None:
            self.query_to_master(self._rewrap(message, payload, metadata))
        else:
            error_bus = Message("hive.query.timeout",
                                {"query_id": query_id, "error": "no_answer"})
            client.send(self._build_query_response(
                HiveMessageType.QUERY, error_bus, query_id,
                originator_peer, self._node_id, route=message.route))

    def cascade_from_master(self, message: HiveMessage) -> None:
        """Relay a CASCADE received from the upstream master.

        As with QUERY, a response goes back to the peer that asked
        (NODE-1 §5.2); only requests fan out downstream.
        """
        if (message.metadata or {}).get("is_response"):
            self._route_query_response(message, None)
            return
        # As with query_from_master: a master-originated cascade binds no
        # downstream return path here, so its response drops at
        # _route_query_response (behavior unchanged by participation binding).
        self._relay_downstream(message)

    def cascade_to_master(self, message: HiveMessage) -> None:
        """Forward a CASCADE envelope upstream. No-op at the top-level master."""
        if self._upstream_hm is None:
            return
        self._upstream_hm.emit(message)

    def handle_cascade_message(self, message: HiveMessage,
                               client: HiveMindClientConnection):
        """CASCADE — like PROPAGATE but every node may answer. Request: try the
        local agent, forward to all other peers + upstream, relay responses
        (collected for disambiguation at the originator). Response: route
        downstream toward the originator."""
        LOG.info(f"Received CASCADE from: {client.peer}")
        metadata = message.metadata or {}
        if not client.can_propagate:
            # See the matching comment in handle_query_message: the
            # is_response branch below trusts an attacker-supplied
            # originator_peer as a delivery address, so it must be gated by
            # the same permission as the request branch, not skipped ahead
            # of it (HIVEMIND-AGENT-1 §3.2).
            LOG.warning("Received CASCADE from client without propagate "
                        "permission")
            if self.illegal_callback:
                self.illegal_callback(self._unpack_message(message, client))
            client.disconnect()
            return

        if metadata.get("is_response", False):
            self._route_query_response(message, client)
            return

        payload = self._unpack_message(message, client)

        # HIVEMIND-MSG-1 §5 gates re-forwarding of a looped message, not local
        # handling; suppress only the fan-out + master-forward at the end.
        looped = self._is_routing_loop(message)
        # MSG-1 §5: name ourselves in the route before forwarding
        if not looped:
            self._append_self_hop(payload)

        query_id = metadata.get("query_id", str(uuid.uuid4()))
        originator_peer = metadata.get("originator_peer", client.peer)
        # participation binding (MSG-1 §5.2): bind this cascade to the arriving
        # connection (client.peer) before _answer_query_locally below, whose
        # CASCADE answer routes THROUGH _route_query_response — the return path
        # must already exist or the node would drop its own answer.
        self._record_outstanding_query(query_id, client.peer)
        try:
            bus = self.get_bus(client)
        except ConnectionError as e:
            self._send_backend_unavailable(client, message, e)
            return
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

        cascade_fwd = self._rewrap(message, payload, metadata)
        plaintext = cascade_fwd.serialize()
        for conn in list(self.clients.values()):
            if conn.peer == client.peer:
                continue
            try:
                conn.send(cascade_fwd, plaintext)
            except Exception:
                LOG.exception(f"failed to forward to {conn.peer}")
        self.cascade_to_master(cascade_fwd)

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
        self.escalate_to_master(self._rewrap(message, payload))

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

                # Two envelope shapes reach this point.
                #
                # Hybrid (``encrypted_key`` present) is what
                # ``HiveMessageBusClient.emit_intercom`` produces: a random
                # AES-256-GCM key encrypts the payload and RSA encrypts only
                # that key. Plain RSA over the whole body is the older shape,
                # still accepted so an existing peer keeps working.
                #
                # Only hybrid can carry a real message. Raw RSA is capped at
                # one block - about 214 bytes with a 2048-bit key - which a
                # serialized BUS envelope barely fits, so a node that only
                # spoke plain RSA could not receive anything substantial.
                #
                # The signature is computed over ``ciphertext`` in both
                # shapes, so the verification above applies unchanged.
                if "encrypted_key" in pload:
                    decrypted: str = hybrid_decrypt(private_key, pload).decode("utf-8")
                else:
                    decrypted: str = decrypt_RSA(private_key, ciphertext).decode("utf-8")
                inner = HiveMessage.deserialize(decrypted)
            except:
                if k:
                    # explicitly addressed to us and undecryptable: drop it
                    LOG.error("failed to decrypt message!")
                    return True
                LOG.debug("failed to decrypt message, not for us")
                return False
        elif self.require_crypto:
            # No signed envelope, so no origin signature to verify: this frame
            # carries no proof of who sent it. HIVEMIND-CRYPTO-1 §5 requires
            # the origin signature, and this listener advertises
            # "crypto_required" to its clients — honour it and drop.
            # Dropping returns True: consumed here, not relayed nor escalated.
            LOG.warning(f"INTERCOM from {client.peer} is unencrypted and "
                        f"unsigned, but this node requires crypto: dropping "
                        f"unauthenticated message")
            return True
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
    @staticmethod
    def _layer1_session_id(client: HiveMindClientConnection, is_admin: bool,
                           declared_id: str) -> str:
        """The Layer-1 (orchestrator) session id for a message declaring
        ``declared_id``: the raw declared id for an admin, or the
        identity-scoped NATted id ``session_namespace:declared_id`` for
        everyone else (HIVEMIND-BRIDGE-1 §4). ``declared_id`` is the
        per-message session id (session travels per message; the client
        declares it), falling back to the connection's HELLO baseline when
        the message declares none. Shared by ``_install_client_session`` and
        the post-transformer re-stamp in ``handle_inject_agent_msg`` so both
        apply the exact same decision to the same message.

        BRIDGE-1 §4: the namespace token IDENTIFIES, it does not
        AUTHENTICATE — possession grants nothing; admission still runs the
        ACL. It is derived from the durable client identity (via
        ``client.session_namespace``), not the secret access key, so a
        session is a durable route that survives reconnect, and hub-salted
        so it is not linkable across hubs. Using the durable identity rather
        than the per-connection ``conn_nonce`` is what keeps a session
        routable across a reconnect (a new connection reuses the same
        namespace) and across a hub restart (the salt is the persistent node
        identity).
        """
        return declared_id if is_admin else f"{client.session_namespace}:{declared_id}"

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
        if not isinstance(raw_session, dict):
            raw_session = {}
        # ``client.sess`` is the connection's HELLO-established baseline. Start
        # from it and OVERLAY the per-message declared session's present,
        # non-null fields (merge, not replace): a thin control message keeps
        # the baseline's location/lang/etc., while a rich message overrides
        # them. The overlay is taken from the raw wire dict, NEVER by building
        # a fresh Session (Session.__init__ fabricates Configuration() defaults
        # — e.g. the master's own location — for absent fields, which would
        # clobber the satellite's real values; that was the session-contents
        # bleed bug).
        session = client.sess.serialize()
        overlay = {k: v for k, v in raw_session.items() if v is not None}
        session.update(overlay)
        if raw_session.get("pipeline") is None:
            # Each bus message owns its outbound pipeline; do not reattach
            # one from the baseline. Per SESSION-1 §2 an explicit null
            # pipeline is malformed and treated as absent; strip it here
            # explicitly (serializers may render a None pipeline as [], which
            # the generic null-strip below would not catch).
            session.pop("pipeline", None)
        # SESSION-1 §2: strip null-valued fields — null is malformed, treat as absent.
        session = {k: v for k, v in session.items() if v is not None}
        # HIVEMIND-BRIDGE-1 §4: session_id is a Layer-1 (orchestrator) identity
        # that OVOS SessionManager keys conversational state on. The client
        # picks it arbitrarily, so two peers choosing the same value (e.g. both
        # "default") would otherwise collide onto one OVOS session. Translate
        # it at this inbound boundary to a per-connection id; every other
        # session field is passed through unchanged.
        # This translation only applies to non-admin connections. An admin is
        # trusted to skip it and address the orchestrator's sessions directly
        # (including the reserved, device-local "default"), per BRIDGE-1
        # §4/§4.1. Admin standing now gates that un-NATted write access, so
        # (like ``MessageTypeACLPolicy`` does for ``allowed_types``) it is
        # re-checked from the DB here rather than trusted from the
        # connect-time snapshot — an operator revoking admin on a live
        # connection takes effect within ``resolve_user``'s TTL instead of
        # only on reconnect. Fall back to the connection snapshot only when
        # the DB row can't be resolved at all.
        db = getattr(self, "db", None)
        user = None
        if db is not None:
            try:
                user = client.resolve_user(db)
            except Exception:
                LOG.exception("_install_client_session: failed to resolve user for admin check")
        is_admin = user.is_admin if user is not None else client.is_admin
        declared_id = raw_session.get("session_id") or client.sess.session_id
        session["session_id"] = self._layer1_session_id(client, is_admin, declared_id)
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

        # Capture the per-message declared session id BEFORE
        # _install_client_session rewrites context["session"]["session_id"]
        # to the derived Layer-1 id. The post-transformer re-stamp below
        # re-derives from this raw declared id, not from the already-NATted
        # value, so it re-asserts the SAME Layer-1 id instead of double-NATting.
        _raw_declared = message.context.get("session") or {}
        declared_id = (_raw_declared.get("session_id")
                       if isinstance(_raw_declared, dict) else None) \
            or client.sess.session_id

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

        # OVOS transformer pipelines: rewrite utterances / context before
        # they reach the agent bus. A cancellation terminates the lifecycle
        # here, the message never reaches the agent.
        if message.msg_type == "recognizer_loop:utterance":
            message = self._apply_utterance_transformers(message, client)
            if message is None:
                return

        # send client message to internal mycroft bus
        LOG.info(f"Forwarding message '{message.msg_type}' to agent bus from client: {client.peer}")
        message.context["peer"] = message.context["source"] = client.peer
        # A metadata/utterance transformer wholesale-replaces message.context
        # (see _apply_utterance_transformers), which could otherwise let a
        # config-opt-in transformer plugin move this message into another
        # client's Layer-1 session (e.g. write "default" back into
        # context["session"]["session_id"]) just like peer/source above must
        # be re-stamped, the session id installed by _install_client_session
        # is re-asserted here, after the transformer chain has run and right
        # before the message reaches the agent bus (HIVEMIND-BRIDGE-1 §4).
        # A transformer plugin can block long enough (an LLM call, a network
        # round trip) for the DB row to change mid-flight, so is_admin is
        # re-resolved fresh here too, same as _install_client_session, rather
        # than re-asserting the dispatch-time snapshot taken before the chain ran.
        db = getattr(self, "db", None)
        user = None
        if db is not None:
            try:
                user = client.resolve_user(db)
            except Exception:
                LOG.exception("handle_inject_agent_msg: failed to resolve user for admin check")
        is_admin = user.is_admin if user is not None else client.is_admin
        client.is_admin = is_admin
        session = message.context.get("session")
        if not isinstance(session, dict):
            session = {}
        session["session_id"] = self._layer1_session_id(client, is_admin, declared_id)
        message.context["session"] = session

        try:
            bus = self.get_bus(client)
        except ConnectionError as e:
            # the chain already admitted this message — the peer must hear
            # that it was not delivered instead of waiting for an answer
            # that will never come. observe() stays unrun: nothing was
            # forwarded, so there is nothing to observe.
            self._send_backend_unavailable(client, message, e)
            return
        bus.emit(message)

        self.policy_chain.observe(message, client)

        if self.agent_bus_callback:
            self.agent_bus_callback(message)

    def _apply_utterance_transformers(self, message: Message,
                                      client: HiveMindClientConnection
                                      ) -> Optional[Message]:
        """Run the utterance + metadata transformer chains on an inbound
        ``recognizer_loop:utterance`` message.

        Returns the (possibly rewritten) message, or ``None`` when a
        transformer canceled the utterance — in that case the terminal
        events are sent back to the client and the message is not injected
        into the agent bus.
        """
        if not (self.utterance_transformers.plugins
                or self.metadata_transformers.plugins):
            return message
        utterances = message.data.get("utterances") or []
        context = dict(message.context)
        if self.utterance_transformers.plugins:
            utterances, context = self.utterance_transformers.transform(
                utterances, context)
        if not context.get("canceled") and self.metadata_transformers.plugins:
            context = self.metadata_transformers.transform(context)
        message.data["utterances"] = utterances
        message.context = context
        if context.get("canceled"):
            LOG.info(f"utterance from {client.peer} canceled by "
                     f"{context.get('cancel_by')}: {context.get('cancel_reason')}")
            # terminal path: cancelled -> handled
            for msg_type in ("ovos.utterance.cancelled", "ovos.utterance.handled"):
                try:
                    client.send(HiveMessage(
                        HiveMessageType.BUS,
                        payload=message.forward(msg_type,
                                                {"cancel_reason": context.get("cancel_reason"),
                                                 "cancel_by": context.get("cancel_by")})))
                except Exception:
                    LOG.exception(f"failed to send {msg_type} to {client.peer}")
            return None
        return message

    def _send_policy_denied(self, client: HiveMindClientConnection,
                             message: Message, verdict) -> None:
        """Inform a client that an admission policy denied their message."""
        self._send_denied(client, getattr(message, "msg_type", None),
                          verdict.code, verdict.reason, verdict.data)

    def _send_backend_unavailable(self, client: HiveMindClientConnection,
                                  message: Union[Message, HiveMessage],
                                  error: Exception) -> None:
        """Inform a client that its message was admitted but could not be
        delivered, because the agent bus behind this node is unreachable."""
        msg_type = str(message.msg_type)
        LOG.error(f"can not forward '{msg_type}' from {client.peer}, "
                  f"the agent bus is unreachable: {error}")
        self._send_denied(client, msg_type, BACKEND_UNAVAILABLE, str(error), {})

    def _send_denied(self, client: HiveMindClientConnection,
                     denied_type: Optional[str], code: str, reason: str,
                     data: dict) -> None:
        payload = Message(
            "hive.policy.denied",
            {
                "denied_type": denied_type,
                "code": code,
                "reason": reason,
                "data": data,
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
