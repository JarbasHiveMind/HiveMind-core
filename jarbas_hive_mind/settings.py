from os import makedirs
from os.path import isdir, join, expanduser

DATA_PATH = expanduser("~/jarbasHiveMind")

if not isdir(DATA_PATH):
    makedirs(DATA_PATH)

CERTS_PATH = join(DATA_PATH, "certs")
if not isdir(CERTS_PATH):
    makedirs(CERTS_PATH)


DB_PATH = join(DATA_PATH, "database")
if not isdir(DB_PATH):
    makedirs(DB_PATH)

CLIENTS_DB = "sqlite:///" + join(DB_PATH, "clients.db")

DEFAULT_PORT = 5678
USE_SSL = False

LOG_BLACKLIST = []

MYCROFT_WEBSOCKET_CONFIG = {
    "host": "0.0.0.0",
    "port": 8181,
    "route": "/core",
    "ssl": False
}

STT_CONFIG = {"stt": {
    "module": "google",
    "deepspeech_server": {
        "uri": "http://localhost:8080/stt"
    },
    "kaldi": {
        "uri": "http://localhost:8080/client/dynamic/recognize"
    }
}}

LISTENER_CONFIG = {
    "listener": {
        "sample_rate": 16000,
        "channels": 1,
        "record_wake_words": False,
        "record_utterances": False,
        "phoneme_duration": 120,
        "multiplier": 1.0,
        "energy_ratio": 1.5,
        "wake_word": "hey mycroft",
        "stand_up_word": "wake up"
    },
    "hotwords": {
        "hey mycroft": {
            "module": "pocketsphinx",
            "phonemes": "HH EY . M AY K R AO F T",
            "threshold": 1e-90,
            "lang": "en-us"
        },
        "thank you": {
            "module": "pocketsphinx",
            "phonemes": "TH AE NG K . Y UW .",
            "threshold": 1e-1,
            "listen": False,
            "utterance": "thank you",
            "active": False,
            "sound": "",
            "lang": "en-us"
        },
        "wake up": {
            "module": "pocketsphinx",
            "phonemes": "W EY K . AH P",
            "threshold": 1e-20,
            "lang": "en-us"
        }
    }
}
