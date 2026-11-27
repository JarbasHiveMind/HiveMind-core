"""The hub owns its identity file under ``hivemind/hivemind-core/``.

hivemind-bus-client refuses to create a private key beside the shared
``hivemind/_identity.json`` for an identity with no ``app_name``
(HIVEMIND-CRYPTO-1 §2), so a hub with a bare ``NodeIdentity()`` starts with no
node public key. A hub that already has a key in the shared file keeps it:
the Noise PSK salt and every client pin depend on it.
"""
import json
import os
from unittest.mock import MagicMock, patch

from Cryptodome.PublicKey import RSA

from hivemind_core.service import HiveMindService


def _service():
    with patch("hivemind_core.service.ClientDatabase", MagicMock()):
        return HiveMindService(db=MagicMock())


def test_a_fresh_hub_gets_a_key_in_its_own_identity_file():
    config = os.environ["XDG_CONFIG_HOME"]
    service = _service()

    assert service.identity.public_key
    own = os.path.join(config, "hivemind", "hivemind-core", "_identity.json")
    assert service.identity.IDENTITY_FILE.path == own
    with open(own) as f:
        assert json.load(f)["public_key"] == service.identity.public_key
    assert not os.path.exists(os.path.join(config, "hivemind", "_identity.json"))


def test_a_hub_with_a_shared_key_keeps_it():
    config = os.environ["XDG_CONFIG_HOME"]
    shared_dir = os.path.join(config, "hivemind")
    os.makedirs(shared_dir)
    key = RSA.generate(2048)
    pem = os.path.join(shared_dir, "HiveMindComs.pem")
    with open(pem, "wb") as f:
        f.write(key.export_key())
    public = key.publickey().export_key().decode("utf-8")
    shared = os.path.join(shared_dir, "_identity.json")
    with open(shared, "w") as f:
        json.dump({"public_key": public, "secret_key": pem}, f)

    service = _service()

    assert service.identity.public_key == public
    with open(shared) as f:
        assert json.load(f)["public_key"] == public
    assert not os.path.exists(
        os.path.join(shared_dir, "hivemind-core", "_identity.json"))
