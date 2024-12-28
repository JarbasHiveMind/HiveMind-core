from hivemind_core.service import HiveMindService
from ovos_bus_client.hpm import OVOSProtocol
from hivemind_websocket_protocol import HiveMindWebsocketProtocol

def main():

    service = HiveMindService(agent_protocol=OVOSProtocol,
                              network_protocol=HiveMindWebsocketProtocol)
    service.run()


if __name__ == "__main__":
    main()
