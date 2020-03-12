import upnpclient
import threading
from time import sleep
from jarbas_utils.log import LOG
from jarbas_utils.xml_helper import xml2dict
from jarbas_hive_mind.slave import HiveMindSlave
from jarbas_hive_mind.slave.terminal import HiveMindTerminal
import requests


class HiveMindNode:
    def __init__(self, d):
        self.device = d
        self._data = None

    @property
    def services(self):
        return self.device.service_map

    @property
    def xml(self):
        return self.device.location

    @property
    def device_name(self):
        return self.device.device_name

    @property
    def friendly_name(self):
        return self.device.friendly_name

    @property
    def description(self):
        return self.device.model_description

    @property
    def node_tyoe(self):
        return self.device.model_name

    @property
    def version(self):
        return self.device.model_number

    @property
    def device_id(self):
        return self.device.udn

    @property
    def data(self):
        if self.xml and self._data is None:
            xml = requests.get(self.xml).text
            self._data = xml2dict(xml)
        return self._data

    @property
    def address(self):
        try:
            services = self.data["root"]["device"]['serviceList']
            for s in services:
                service = services[s]
                if service["serviceType"] == \
                        'urn:jarbasAi:HiveMind:service:Master':
                    return service["URLBase"]
        except:
            return None

    @property
    def host(self):
        return ":".join(self.address.split(":")[:-1])

    @property
    def port(self):
        return int(self.address.split(":")[-1])

    def connect(self, headers, crypto_key=None, bus=None,
                node_type=None):
        try:
            # TODO cyclic import
            from jarbas_hive_mind import HiveMindConnection
            con = HiveMindConnection(self.host, self.port)
            if node_type:
                clazz = node_type
            else:
                if bus:
                    clazz = HiveMindSlave
                else:
                    clazz = HiveMindTerminal
            if bus:
                component = clazz(bus=bus,
                                  headers=headers,
                                  crypto_key=crypto_key)
            else:
                component = clazz(headers=headers,
                                  crypto_key=crypto_key)
            # will check url for ssl
            LOG.debug("Connecting to HiveMind websocket @ {url}".format(
                url=self.address))
            con.connect(component)
        except Exception as e:
            LOG.error("Connection failed")
            LOG.exception(e)


class LocalDiscovery(threading.Thread):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pause = 20  # scan every 20 seconds
        self._nodes = {}
        self.running = False

    @property
    def nodes(self):
        return self._nodes

    def scan(self):
        devices = upnpclient.discover()
        for d in devices:
            if d.location in self.nodes:
                continue
            if d.model_name == "HiveMind-core":
                node = HiveMindNode(d)
                LOG.info("Discovered Node: {name} / {url}".format(
                    name=node.friendly_name, url=node.address))
                self._nodes[node.xml] = node
                yield node.xml
        sleep(self.pause)

    def run(self) -> None:
        self.running = True
        while self.running:
            self.scan()

    def stop(self):
        self.running = False

    def search_and_connect(self, *args, **kwargs):
        blacklist = []
        while True:
            for node_url in self.scan():
                if node_url in blacklist:
                    continue
                LOG.info("Fetching Node data: {url}".format(url=node_url))
                node = self.nodes[node_url]
                node.connect(*args, **kwargs)
                blacklist.append(node_url)