import dataclasses
from typing import Callable, Optional, Type

from ovos_utils.log import LOG
from ovos_utils.process_utils import ProcessStatus, StatusCallbackMap

from hivemind_bus_client.identity import NodeIdentity
from hivemind_core.config import get_server_config
from hivemind_core.database import ClientDatabase
from hivemind_core.protocol import HiveMindListenerProtocol, ClientCallbacks
from hivemind_plugin_manager import AgentProtocolFactory, NetworkProtocolFactory, BinaryDataHandlerProtocolFactory
from hivemind_plugin_manager.protocols import BinaryDataHandlerProtocol

def get_agent_protocol():
    config = get_server_config()["agent_protocol"]
    name = config["module"]
    return AgentProtocolFactory.get_class(name), config.get(name, {})


def get_network_protocol():
    config = get_server_config()["network_protocol"]
    name = config["module"]
    return NetworkProtocolFactory.get_class(name), config.get(name, {})


def get_binary_protocol():
    config = get_server_config()["binary_protocol"]
    name = config["module"]
    if name is None: # binary protocol is optional
        # dummy by default
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
    """
    A service that manages the HiveMind protocol, including agent communication,
    database interactions, and network management.

    Attributes:
        identity (NodeIdentity): The identity of the node in the HiveMind network.
        db (ClientDatabase): The database used for storing client information.
        hm_protocol (Type[HiveMindListenerProtocol]): The protocol for handling HiveMessages.
        alive_hook (Callable[[None], None]): Hook called when the service is alive.
        started_hook (Callable[[None], None]): Hook called when the service has started.
        ready_hook (Callable[[None], None]): Hook called when the service is ready.
        error_hook (Callable[[Exception], None]): Hook called when an error occurs.
        stopping_hook (Callable[[None], None]): Hook called when the service is stopping.
        _status (Optional[ProcessStatus]): The current status of the service.
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
        self._status.set_alive()

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

        # start network protocol that will deliver HiveMessages
        network_class, net_config = get_network_protocol()
        LOG.info(f"Network protocol: {network_class.__name__}")

        network_protocol = network_class(hm_protocol=hm_protocol, config=net_config)

        self._status.set_ready()

        network_protocol.run()  # blocking

        self._status.set_stopping()
