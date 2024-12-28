from hivemind_core.service import HiveMindService
from hivemind_core.agents import OVOSProtocol
from hivemind_core.server import HiveMindWebsocketProtocol

def main():

    service = HiveMindService(agent_protocol=OVOSProtocol,
                              network_protocol=HiveMindWebsocketProtocol)
    service.run()


if __name__ == "__main__":
    main()
