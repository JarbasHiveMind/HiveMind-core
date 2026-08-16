# hivemind-core
# Copyright (C) 2026 Casimiro Ferreira
# SPDX-License-Identifier: Apache-2.0
import dataclasses
from os.path import isfile
import ipaddress
import socket
import threading
import time
from typing import Callable, Mapping, Optional, Type


from ovos_utils import create_daemon, wait_for_exit_signal
from ovos_utils.log import LOG
from ovos_utils.process_utils import ProcessStatus, StatusCallbackMap

from hivemind_bus_client.client import HiveMessageBusClient
from hivemind_bus_client.fakebus import FakeBus
from hivemind_bus_client.identity import NodeIdentity
from poorman_handshake.asymmetric.utils import load_RSA_key
from hivemind_bus_client.protocol import HiveMindSlaveProtocol
from hivemind_core.config import get_server_config, upstream_config
from hivemind_core.database import ClientDatabase
from hivemind_core.protocol import HiveMindListenerProtocol, ClientCallbacks
from hivemind_plugin_manager import AgentProtocolFactory, NetworkProtocolFactory, BinaryDataHandlerProtocolFactory
from hivemind_plugin_manager.protocols import BinaryDataHandlerProtocol


def get_agent_protocol():
    config = get_server_config()["agent_protocol"]
    name = config["module"]
    return AgentProtocolFactory.get_class(name), config.get(name, {})


def get_binary_protocol():
    config = get_server_config()["binary_protocol"]
    name = config["module"]
    if name is None:
        # the binary protocol is optional; the base class is a no-op handler
        return BinaryDataHandlerProtocol, {}
    return BinaryDataHandlerProtocolFactory.get_class(name), config.get(name, {})


#: hosts that mean "this machine" to a listener or a client
_LOOPBACK = {"127.0.0.1", "::1", "localhost", "localhost.localdomain"}
#: hosts a listener binds to mean "every interface on this machine"
_WILDCARD = {"", "0.0.0.0", "::", "*"}


def _is_this_machine(host: str) -> bool:
    """Whether ``host`` names the machine this node runs on."""
    host = str(host).strip().lower().strip("[]")
    for scheme in ("ws://", "wss://", "http://", "https://"):
        if host.startswith(scheme):
            host = host[len(scheme):]
    host = host.rstrip("/")
    if host in _LOOPBACK or host in _WILDCARD:
        return True
    if host == socket.gethostname().lower():
        return True
    try:
        return ipaddress.ip_address(socket.gethostbyname(host)).is_loopback
    except (socket.gaierror, ValueError, UnicodeError):
        return False


def own_listener_for(host: str, port: int, network_protocol: Mapping) -> Optional[str]:
    """The name of this node's own listener that ``host:port`` points at, or
    None when the endpoint belongs to some other node.

    An upstream aimed at this node's own listener connects, gets rejected,
    reconnects five seconds later and does that forever, emitting a
    ``hive.client.connection.error`` on the bus every time — the reconnect
    counter never backs off, because each attempt does connect. Better to
    refuse the loop at startup.

    A listener bound to ``0.0.0.0`` answers on every address of this machine,
    so ``127.0.0.1`` reaches it just as ``0.0.0.0`` would: the comparison is
    "same machine and same port", not "same host string".
    """
    if not _is_this_machine(host):
        return None
    for name, conf in network_protocol.items():
        if not isinstance(conf, Mapping) or conf.get("port") is None:
            continue
        if int(conf["port"]) != int(port):
            continue
        listener_host = str(conf.get("host", "")).strip().lower()
        if listener_host in _WILDCARD or _is_this_machine(listener_host):
            return name
    return None


def _ensure_node_identity(identity: NodeIdentity) -> None:
    """Give an identity a public key if it does not have one yet.

    ``NodeIdentity`` reads its JSON file and returns ``None`` for a key that
    was never generated. Nothing on the server path generates one:
    ``hivemind-client set-identity`` does, but that is the client CLI, and an
    operator who only ever runs ``hivemind-core`` never calls it. The node then
    runs with ``_node_id is None`` for its whole life, and the public key is
    not decoration:

    * It is the ``peer`` of every responsive PING the node sends, so an unkeyed
      node answers a flood anonymously and no client can put it on the hive
      map. Observed live: ``hivemind-client ping`` printing
      "[No responses received]" against a node that was answering.
    * It is the hop identity for MSG-1 §5 loop suppression. ``_append_self_hop``
      stamps ``{"source": _node_id}`` and ``HiveMessage.route`` drops any hop
      with a falsy ``source``, so an unkeyed node never appears in a route and
      never recognises its own — a flood is not suppressed at all.
    * It is how the mesh addresses this node end-to-end (INTERCOM
      ``target_pubkey``), so mail to it cannot be addressed.

    A node has one identity and uses it in both directions: the key it answers
    its own clients with is the key it announces to its master. A relay without
    one is mapped as an anonymous client, and its two halves cannot be
    recognised as one node.

    Generating is idempotent: it happens only when the field is empty, and the
    key is persisted so it stays stable across restarts, which is the property
    everything above depends on. Failure is not fatal. A read-only or
    root-owned config directory is a normal container shape, and a node that
    served clients yesterday must not refuse to boot today over a key it can
    live without.
    """
    if identity.public_key:
        return
    # A configured private key is the node's identity even when the JSON
    # carries no public_key field: create_keys() writes a fresh keypair to a
    # fixed filename and rewrites secret_key, so generating here would orphan
    # the operator's key and rotate the identity everything else pinned.
    # Publish the public half of the key that is already in use instead.
    configured = identity.IDENTITY_FILE.get("secret_key")
    if configured and isfile(configured):
        try:
            identity.public_key = load_RSA_key(configured).publickey(
                ).export_key().decode("utf-8")
            identity.save()
            LOG.info(f"published the public half of {configured}")
            return
        except Exception:
            LOG.exception(f"could not read the configured private key "
                          f"{configured}, generating a new keypair")
    try:
        LOG.info("no node public key found, generating one")
        identity.create_keys()
        identity.save()
        LOG.info(f"node identity saved to {identity.IDENTITY_FILE.path}")
    except Exception:
        LOG.exception("could not generate a node public key, continuing "
                      "without one — this node will be unmappable and cannot "
                      "be addressed by INTERCOM")


def on_ready():
    LOG.info("hivemind-core service ready!")


def on_alive():
    LOG.info("hivemind-core service alive")


def on_started():
    LOG.info("hivemind-core service started!")


def on_error(e="Unknown"):
    LOG.info("hivemind-core failed to start ({})".format(repr(e)))


def on_stopping():
    LOG.info("hivemind-core is shutting down...")


@dataclasses.dataclass
class HiveMindService:
    """The hivemind-core server: agent protocol, client database, and the
    network protocols that carry HiveMessages.

    The ``*_hook`` fields are the ovos-utils ProcessStatus callbacks; replace
    them to report lifecycle transitions somewhere other than the log.
    """
    hm_protocol: Type[HiveMindListenerProtocol] = HiveMindListenerProtocol

    identity: NodeIdentity = dataclasses.field(default_factory=NodeIdentity)
    db: ClientDatabase = dataclasses.field(default_factory=ClientDatabase)
    callbacks: ClientCallbacks = dataclasses.field(default_factory=ClientCallbacks)

    alive_hook: Callable[[], None] = on_alive
    started_hook: Callable[[], None] = on_started
    ready_hook: Callable[[], None] = on_ready
    error_hook: Callable[[Optional[Exception]], None] = on_error
    stopping_hook: Callable[[], None] = on_stopping

    _status: Optional[ProcessStatus] = None
    #: seconds between attempts to build the agent protocol when its backend
    #: is unreachable
    agent_retry_delay: float = 5.0

    def __post_init__(self) -> None:
        self._presence = None
        self._upstream = None
        self._status = self._status or ProcessStatus("HiveMind",
                                                     callback_map=StatusCallbackMap(
                                                         on_started=self.started_hook,
                                                         on_alive=self.alive_hook,
                                                         on_ready=self.ready_hook,
                                                         on_error=self.error_hook,
                                                         on_stopping=self.stopping_hook,
                                                     ))
        self._status.set_alive()
        # after the status hooks exist: a failure in here must be reportable
        _ensure_node_identity(self.identity)

    def _start_presence(self) -> None:
        """Optionally advertise this hivemind-core server on the local network
        via hivemind-presence (UPnP/SSDP and/or zeroconf mDNS). No-op when the
        optional package is not installed or presence is disabled."""
        try:
            from hivemind_presence import LocalPresence
        except ImportError:
            return
        cfg = get_server_config()
        presence_cfg = cfg.get("presence", {})
        if not presence_cfg.get("enabled", True):
            return
        # presence advertises a single endpoint, so the first configured
        # network protocol (websocket, by default ordering) is the one announced
        net = cfg.get("network_protocol", {})
        first = next(iter(net.values()), {})
        self._presence = LocalPresence(
            port=first.get("port", 5678),
            ssl=first.get("ssl", False),
            name=presence_cfg.get("name", "HiveMind-Node"),
            upnp=presence_cfg.get("upnp", False),
            zeroconf=presence_cfg.get("zeroconf", True),
        )
        create_daemon(self._presence.start)
        LOG.info("LocalPresence started")

    def _start_rendezvous(self, hm_protocol: HiveMindListenerProtocol) -> None:
        """Optionally make this node a rendezvous point, holding mail for peers
        that are never online at the same time, via the optional
        hivemind-rendezvous package. No-op when that package is not installed
        or rendezvous is disabled — the node then answers RENDEZVOUS with
        "not_a_rendezvous_node", which is the honest reply.

        Same shape as _start_presence: an optional import, a config switch,
        and nothing else in the process to run or expose. The mailbox is
        served over the listener that is already accepting clients, so being
        a rendezvous node costs no extra port, credential or service.
        """
        try:
            from hivemind_rendezvous import RendezvousMailbox
        except ImportError:
            return
        cfg = get_server_config().get("rendezvous", {})
        if not cfg.get("enabled", False):
            return

        # hivemind-rendezvous 2.0.0a1 (PR #14) switched from keying mailboxes
        # by the recipient's public key to keying them by the authenticated
        # access key, which is what this protocol passes to mailbox.handle().
        # An older package silently accepts deposits under the wrong key and
        # never delivers them, so a too-old install must not be bound at all.
        try:
            from hivemind_rendezvous.version import (
                VERSION_MAJOR, VERSION_MINOR, VERSION_BUILD
            )
            installed = (VERSION_MAJOR, VERSION_MINOR, VERSION_BUILD)
        except (ImportError, AttributeError):
            installed = (0, 0, 0)
        if installed < (2, 0, 0):
            LOG.error(
                f"hivemind-rendezvous>=2.0.0a1 is required for mailbox "
                f"delivery; installed {'.'.join(map(str, installed))} keys "
                f"mailboxes by public key and is incompatible with this "
                f"core's access-key addressing — rendezvous DISABLED, "
                f"upgrade to restore it"
            )
            return

        hm_protocol.mailbox = RendezvousMailbox(
            max_pending_per_mailbox=cfg.get("max_pending_per_mailbox", 256)
        )
        LOG.info("rendezvous mailbox enabled")

    def _connect_upstream(self, hm_protocol: HiveMindListenerProtocol
                          ) -> Optional[HiveMindSlaveProtocol]:
        """Optionally connect this node to a master above it
        (HIVEMIND-NODE-1 §3.3/§4).

        Returns the bound ``HiveMindSlaveProtocol``, or None when no upstream
        is configured — then the node is a top-level master, as before.

        The websocket is opened on a daemon thread. ``connect`` blocks until
        the handshake completes, so doing it inline would hold up startup for
        as long as the master is unreachable. The client owns its own reconnect
        loop, so once started it keeps retrying on its own.
        """
        server_config = get_server_config()
        config = upstream_config(server_config)
        if not config["enabled"]:
            return None

        if not config["key"] or not config["password"]:
            # Serving the downstream clients matters more than reaching the
            # master: come up as a top-level master and say so, loudly. Raising
            # here would abort startup and take every satellite offline over a
            # typo in one config key.
            LOG.error("upstream is enabled but 'key' and 'password' are not "
                      "both set in server.json — staying a top-level master. "
                      "Run 'hivemind-core add-client' ON THE MASTER and copy "
                      "the credentials it prints into the upstream block.")
            return None

        own = own_listener_for(config["host"], config["port"],
                               server_config.get("network_protocol") or {})
        if own is not None:
            LOG.error(f"upstream points at this node's own '{own}' listener "
                      f"({config['host']}:{config['port']}) — staying a "
                      f"top-level master. A node can not be its own master: "
                      f"the link would connect, be rejected and reconnect "
                      f"every few seconds forever. Point 'upstream' at the "
                      f"master above this node.")
            return None

        scheme = "wss://" if config["ssl"] else "ws://"
        upstream = HiveMessageBusClient(key=config["key"],
                                        password=config["password"],
                                        host=scheme + config["host"],
                                        port=config["port"],
                                        self_signed=config["self_signed"],
                                        identity=self.identity)
        slave = HiveMindSlaveProtocol(hm=upstream)
        hm_protocol.bind_upstream(slave)
        LOG.info(f"Upstream master: {config['host']}:{config['port']}")

        def connect():
            try:
                # `connect` binds the slave to the bus before opening the
                # socket; the upstream link shares no local OVOS bus
                upstream.connect(bus=FakeBus(), protocol=slave,
                                 site_id=self.identity.site_id)
            except Exception:
                LOG.exception("Failed to connect to the upstream master, "
                              "retrying in the background")

        create_daemon(connect)
        self._upstream = slave
        return slave

    def _start_agent_protocol(self, agent_class: Type, config: Mapping):
        """Build the agent protocol, retrying while its backend is unreachable.

        Agents are expected to degrade rather than raise: the OVOS plugin comes
        up with a disconnected bus, its client reconnects on its own, and Core
        answers BACKEND_UNAVAILABLE meanwhile — the node serves its satellites
        the whole time. An agent that insists on raising leaves nothing to
        build the listeners around, so keep trying instead of exiting: on a
        slow board the OVOS messagebus is simply a few seconds behind, and
        exiting would take the whole hive down until someone restarts us.
        """
        while True:
            try:
                return agent_class(config=config)
            except ConnectionError as e:
                LOG.error(f"{agent_class.__name__} can not reach its backend "
                          f"({e}); retrying in {self.agent_retry_delay}s. No "
                          f"client can be served until it answers.")
                time.sleep(self.agent_retry_delay)

    def _run_network_protocols(self, protos: list) -> None:
        """Start every network protocol on its own daemon thread.

        ``run`` blocks on an IOLoop, so an exception in it (a port already in
        use, an unreadable SSL certificate) kills its thread and nothing else.
        Unwatched, the service would report itself ready while carrying no
        traffic at all. One dead transport is survivable — the others still
        serve — but a node with every transport dead is in error, and must say
        so instead of looking healthy.
        """
        alive = len(protos)
        lock = threading.Lock()

        def run(network_protocol):
            nonlocal alive
            try:
                network_protocol.run()
            except Exception:
                LOG.exception(f"Network protocol "
                              f"{type(network_protocol).__name__} stopped")
            with lock:
                alive -= 1
                dead = alive == 0
            if dead:
                LOG.error("Every network protocol has stopped, this node no "
                          "longer accepts clients")
                self._status.set_error("all network protocols stopped")

        # ready first: set_ready and set_error are plain assignments, so a
        # transport that fails the moment it starts (port already bound,
        # unreadable certificate) would set_error before this line ran and
        # the node would end up READY with nothing listening
        self._status.set_ready()

        for network_protocol in protos:
            create_daemon(run, (network_protocol,))

    def _stop_upstream(self) -> None:
        if self._upstream is not None:
            self._upstream.hm.close()

    def _stop_presence(self) -> None:
        if self._presence is not None:
            self._presence.stop()

    def run(self):
        self._status.set_started()

        # start/connect agent protocol that will handle HiveMessage payloads
        agent_class, agent_config = get_agent_protocol()
        LOG.info(f"Agent protocol: {agent_class.__name__}")

        agent_protocol = self._start_agent_protocol(agent_class, agent_config)
        self._status.bind(agent_protocol.bus)

        # binary data handling protocol
        bin_class, bin_config = get_binary_protocol()
        LOG.info(f"BinaryData protocol: {bin_class.__name__}")

        bin_protocol = bin_class(agent_protocol=agent_protocol, config=bin_config)

        # start hivemind protocol that will handle HiveMessages
        hm_protocol = self.hm_protocol(identity=self.identity,
                                       db=self.db,
                                       callbacks=self.callbacks,
                                       binary_data_protocol=bin_protocol,
                                       agent_protocol=agent_protocol)

        # optionally hold mail for peers that are never online together
        self._start_rendezvous(hm_protocol)

        # optionally connect this node to a master above it
        self._connect_upstream(hm_protocol)

        # start network protocols that will carry HiveMessages
        protos = []
        for plug_name, plug_conf in get_server_config()["network_protocol"].items():
            try:
                network_class = NetworkProtocolFactory.get_class(plug_name)
                LOG.info(f"Network protocol: {network_class.__name__}")
                protos.append(network_class(hm_protocol=hm_protocol, config=plug_conf))
            except Exception:
                # one broken transport must not take down the others; the
                # empty-protos check below still aborts startup if all fail
                LOG.exception(f"Failed to load plugin '{plug_name}'")

        if not protos:
            LOG.error("No network protocols were loaded. Exiting service.")
            self._status.set_stopping()
            return

        self._run_network_protocols(protos)

        self._start_presence()
        wait_for_exit_signal()  # block until ctrl+c

        self._stop_presence()
        self._stop_upstream()
        self._status.set_stopping()
