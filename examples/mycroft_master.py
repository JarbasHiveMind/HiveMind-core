from jarbas_hive_mind import HiveMindListener
from jarbas_hive_mind.configuration import CONFIGURATION
from jarbas_utils.log import LOG
from os.path import exists, join


def start_mind(config=None, bus=None):

    config = config or CONFIGURATION

    # read configuration
    port = config["port"]
    max_connections = config.get("max_connections", -1)
    certificate_path = config["ssl"]["certificates"]
    key = join(certificate_path,
               config["ssl"]["ssl_keyfile"])
    cert = join(certificate_path,
                config["ssl"]["ssl_certfile"])

    # generate self signed keys
    if not exists(key):
        LOG.warning("ssl keys dont exist")
        HiveMindListener.generate_keys(certificate_path)

    # listen
    listener = HiveMindListener(port, max_connections, bus)
    listener.secure_listen(key, cert)


if __name__ == '__main__':
    start_mind()

    # that's it, now external applications can connect to the HiveMind

    # use configuration to set things like
    #  - blacklisted/whitelisted ips
    #  - blacklisted/whitelisted message_types
    #  - blacklisted/whitelisted intents - Coming soon
    #  - blacklisted/whitelisted skills  - Coming soon

    # you can send messages to the mycroft bus to send/broadcast to clients
    # 'Message(hive.client.broadcast',
    #           {"payload":
    #               {"msg_type": "speak",
    #               "data": {"utterance": "Connected to the HiveMind"}
    #           })

    # or you can listen to hive mind events
    # "hive.client.connection.error"
    # "hive.client.connect"
    # "hive.client.disconnect"
    # "hive.client.send.error"
