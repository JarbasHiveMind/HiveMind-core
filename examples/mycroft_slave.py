from jarbas_hive_mind import HiveMindConnection
from jarbas_hive_mind.slave import HiveMindSlave


def connect_to_hivemind(host="127.0.0.1", port=5678, name="Jarbas Drone",
                        key="drone_key", useragent="JarbasDroneV0.1", bus=None):
    con = HiveMindConnection(host, port)

    factory = HiveMindSlave(bus=bus, headers=con.get_headers(name, key),
                            useragent=useragent)

    con.secure_connect(factory)


if __name__ == '__main__':
    # TODO arg parse
    connect_to_hivemind()

    # That's it, now the hive mind can send messages to the mycroft bus

    # you can react to hive mind events
    # NOTE the payload from hive mind is also sent directly to the messagebus
    # "hive.mind.connected"
    # "hive.mind.websocket.open"
    # "hive.mind.connection.closed"
    # "hive.mind.message.received"
    # "hive.mind.message.sent"

    # you can send messages to the mycroft bus to send to the HiveMind
    # for example to interact with a skill
    # 'Message("hive.mind.message.send",
    #           {"payload":
    #               {"msg_type": "sensor.data",
    #               "data": {"status": "off"}
    #           })
