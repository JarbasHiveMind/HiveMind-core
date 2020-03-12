from jarbas_hive_mind.discovery import LocalDiscovery
from jarbas_hive_mind import HiveMindConnection
from jarbas_utils.log import LOG


def discover_hivemind(key="dummy_key",
                      name="HiveDummyNode"):
    headers = HiveMindConnection.get_headers(name, key)
    discovery = LocalDiscovery()
    blacklist = []
    while True:
        for node_url in discovery.scan():
            if node_url in blacklist:
                continue
            LOG.info("Fetching Node data: {url}".format(url=node_url))
            node = discovery.nodes[node_url]
            node.connect(headers=headers)

            blacklist.append(node_url)


if __name__ == '__main__':
    # TODO arg parse
    discover_hivemind()
