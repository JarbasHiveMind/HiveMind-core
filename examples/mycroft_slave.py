from jarbas_hive_mind import HiveMindConnection
from jarbas_hive_mind.slave import HiveMindSlave, HiveMindSlaveProtocol


def connect_to_hivemind(host="127.0.0.1", port=5678, name="Jarbas Drone",
                        key="drone_key", useragent="JarbasDroneV0.1", bus=None):
    con = HiveMindConnection(host, port)

    factory = HiveMindSlave(bus=bus, headers=con.get_headers(name, key),
                            useragent=useragent)
    factory.protocol = HiveMindSlaveProtocol

    con.secure_connect(factory)


if __name__ == '__main__':
    # TODO arg parse
    connect_to_hivemind()
