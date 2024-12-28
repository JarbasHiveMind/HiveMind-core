import dataclasses
from typing import Callable, Dict, Any, Optional, Type

from hivemind_presence import LocalPresence
from ovos_utils.log import LOG
from ovos_utils.process_utils import ProcessStatus, StatusCallbackMap

from hivemind_bus_client.identity import NodeIdentity
from hivemind_core.database import ClientDatabase
from hivemind_core.protocol import (
    HiveMindListenerProtocol,
    HiveMindNodeType,
    NetworkProtocol, AgentProtocol
)
from hivemind_core.server import HiveMindWebsocketProtocol


def on_ready():
    LOG.info("HiveMind bus service ready!")


def on_alive():
    LOG.info("HiveMind bus service alive")


def on_started():
    LOG.info("HiveMind bus service started!")


def on_error(e="Unknown"):
    LOG.info("HiveMind bus failed to start ({})".format(repr(e)))


def on_stopping():
    LOG.info("HiveMind bus is shutting down...")


@dataclasses.dataclass
class HiveMindService:
    """
    A service that manages the HiveMind protocol, including agent communication,
    database interactions, and network management.

    Attributes:
        identity (NodeIdentity): The identity of the node in the HiveMind network.
        db (ClientDatabase): The database used for storing client information.
        agent_protocol (Type[AgentProtocol]): The protocol used for agent communication.
        agent_config (Dict[str, Any]): Configuration settings for the agent protocol.
        hm_protocol (Type[HiveMindListenerProtocol]): The protocol for handling HiveMessages.
        hm_config (Dict[str, Any]): Configuration settings for the HiveMind protocol.
        network_protocol (Type[HiveMindWebsocketProtocol]): The protocol for network communication.
        network_config (Dict[str, Any]): Configuration settings for the network protocol.
        alive_hook (Callable[[None], None]): Hook called when the service is alive.
        started_hook (Callable[[None], None]): Hook called when the service has started.
        ready_hook (Callable[[None], None]): Hook called when the service is ready.
        error_hook (Callable[[Exception], None]): Hook called when an error occurs.
        stopping_hook (Callable[[None], None]): Hook called when the service is stopping.
        _status (Optional[ProcessStatus]): The current status of the service.
        _presence (Optional[LocalPresence]): The local presence object for network discovery.
    """
    # TODO - pluginify
    agent_protocol: Type[AgentProtocol]
    network_protocol: Type[NetworkProtocol]
    hm_protocol: Type[HiveMindListenerProtocol] = HiveMindListenerProtocol
    agent_config: Dict[str, Any] = dataclasses.field(default_factory=dict)
    hm_config: Dict[str, Any] = dataclasses.field(default_factory=dict)
    network_config: Dict[str, Any] = dataclasses.field(default_factory=dict)

    identity: NodeIdentity = dataclasses.field(default_factory=NodeIdentity)
    db: ClientDatabase = dataclasses.field(default_factory=ClientDatabase)

    alive_hook: Callable[[], None] = on_alive
    started_hook: Callable[[], None] = on_started
    ready_hook: Callable[[], None] = on_ready
    error_hook: Callable[[Optional[Exception]], None] = on_error
    stopping_hook: Callable[[], None] = on_stopping

    _status: Optional[ProcessStatus] = None
    _presence: Optional[LocalPresence] = None

    def __post_init__(self) -> None:
        """
        Initializes the service's status and presence objects after the dataclass
        has been created.
        """
        self._status = self._status or ProcessStatus("HiveMind",
                                                     callback_map=StatusCallbackMap(
                                                         on_started=self.started_hook,
                                                         on_alive=self.alive_hook,
                                                         on_ready=self.ready_hook,
                                                         on_error=self.error_hook,
                                                         on_stopping=self.stopping_hook,
                                                     ))
        self._presence = self._presence or LocalPresence(
            name=self.identity.name,
            service_type=HiveMindNodeType.MIND,
            upnp=self.network_config.get("upnp", False),
            port=self.identity.default_port,
            zeroconf=self.network_config.get("zeroconf", False),
        )

    @property
    def host(self) -> str:
        """
        Returns the host address for the service.

        Returns:
            str: The host address, defaulting to "0.0.0.0" if not specified.
        """
        host = self.network_config.get("host") or self.identity.default_master or "0.0.0.0"
        return host.split("://")[-1]

    @property
    def port(self) -> int:
        return self.network_config.get("port") or self.identity.default_port or 5678

    def run(self):
        self._status.set_alive()
        # start/connect agent protocol that will handle HiveMessage payloads
        agent_protocol = self.agent_protocol(config=self.agent_config)

        self._status.bind(agent_protocol.bus)

        # start hivemind protocol that will handle HiveMessages
        hm_protocol = self.hm_protocol(identity=self.identity,
                                       db=self.db,
                                       agent_protocol=agent_protocol)
        agent_protocol.hm_protocol = hm_protocol # allow it to reference clients/database/identity

        # start network protocol that will deliver HiveMessages
        network_protocol = self.network_protocol(hm_protocol=hm_protocol,
                                                 config=self.network_config)

        self._status.set_started()

        self._presence.start()
        self._status.set_ready()

        network_protocol.run()  # blocking

        self._status.set_stopping()
        self._presence.stop()
