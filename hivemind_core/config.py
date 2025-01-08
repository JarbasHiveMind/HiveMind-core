import os.path

from json_database import JsonStorageXDG
from ovos_utils.xdg_utils import xdg_config_home, xdg_data_home


_DEFAULT = {
    # enable the hivemind binarization protocol
    "binarize": False,  # default False because of a bug in old hivemind-bus-client versions

    # sort encodings by order of preference
    "allowed_encodings": ["JSON-B64", "JSON-URLSAFE-B64",
                          "JSON-B91",
                          "JSON-Z85B", "JSON-Z85P",
                          "JSON-B32", "JSON-HEX"],
    "allowed_ciphers": ["CHACHA20-POLY1305", 'AES-GCM'],

    # configure various plugins
    "agent_protocol": {"module": "hivemind-ovos-agent-plugin",
                       "hivemind-ovos-agent-plugin": {
                           "host": "127.0.0.1",
                           "port": 8181
                       }},
    "binary_protocol": {"module": None},
    "network_protocol": {"hivemind-websocket-plugin": {
                             "host": "0.0.0.0",
                             "port": 5678,
                             "ssl": False,
                             "cert_dir": f"{xdg_data_home()}/hivemind",
                             "cert_name": "hivemind"
                         },
                         "hivemind-http-plugin": {
                             "host": "0.0.0.0",
                             "port": 5679,
                             "ssl": False,
                             "cert_dir": f"{xdg_data_home()}/hivemind",
                             "cert_name": "hivemind"
                         }},
    "database": {"module": "hivemind-json-db-plugin",
                 "hivemind-json-db-plugin": {
                     "name": "clients",
                     "subfolder": "hivemind-core"
                 }}
}
def get_server_config() -> JsonStorageXDG:
    """from ~/.config/hivemind-core/server.json """
    db = JsonStorageXDG("server",
                          xdg_folder=xdg_config_home(),
                          subfolder="hivemind-core")
    if not os.path.isfile(db.path):
        db.merge(_DEFAULT)
        db.store()
    # ensure all top level keys are present
    for k, v in _DEFAULT.items():
        if k not in db:
            db[k] = v
    return db
