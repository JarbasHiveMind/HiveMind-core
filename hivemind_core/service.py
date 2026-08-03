# hivemind-core
# Copyright (C) 2026 Casimiro Ferreira
# SPDX-License-Identifier: Apache-2.0
import dataclasses
from typing import Callable, Optional, Type

from ovos_utils import create_daemon, wait_for_exit_signal
from ovos_utils.log import LOG
from ovos_utils.process_utils import ProcessStatus, StatusCallbackMap

from hivemind_bus_client.client import HiveMessageBusClient
from hivemind_bus_client.fakebus import FakeBus
from hivemind_bus_client.identity import NodeIdentity
from hivemind_bus_client.protocol import HiveMindSlaveProtocol
from hivemind_core.config import get_server_config
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
        config = get_server_config()["upstream"]
        if not config["enabled"]:
            return None

        scheme = "wss://" if config["ssl"] else "ws://"
        upstream = HiveMessageBusClient(key=config["key"],
                                        password=config["password"],
                                        host=scheme + config["host"],
                                        port=config["port"],
                                        self_signed=config["self_signed"])
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

        agent_protocol = agent_class(config=agent_config)
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

        for network_protocol in protos:
            create_daemon(network_protocol.run)

        self._status.set_ready()

        self._start_presence()
        wait_for_exit_signal()  # block until ctrl+c

        self._stop_presence()
        self._stop_upstream()
        self._status.set_stopping()
