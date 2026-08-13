"""A node without a public key cannot be named, mapped or routed around.

`NodeIdentity` returns None for a key that was never generated, and nothing on
the server path generates one: `hivemind-client set-identity` does, but that is
the client CLI. A node started by an operator who only runs `hivemind-core`
therefore has `_node_id is None` for its whole life.

Observed live on hivemind.openvoiceos.pt before this fix: the node answered a
PING flood with `peer: null, public_key: null`, and `hivemind-client ping`
reported "[No responses received]" against a node that was replying.
"""
from unittest.mock import MagicMock, patch

from hivemind_core.protocol import HiveMindListenerProtocol
from hivemind_core.service import HiveMindService


def _service(identity):
    """Build the service without touching the database or the bus."""
    with patch("hivemind_core.service.ClientDatabase", MagicMock()):
        return HiveMindService(identity=identity, db=MagicMock())


def _identity(public_key=None):
    ident = MagicMock()
    ident.public_key = public_key
    ident.IDENTITY_FILE.path = "/tmp/_identity.json"

    def create_keys():
        ident.public_key = "-----BEGIN PUBLIC KEY-----\nGENERATED\n-----END PUBLIC KEY-----"

    ident.create_keys.side_effect = create_keys
    return ident


def test_a_node_with_no_key_generates_one_at_startup():
    ident = _identity(public_key=None)

    _service(ident)

    ident.create_keys.assert_called_once()
    ident.save.assert_called_once(), "a key that is not persisted changes on every restart"
    assert ident.public_key, "the node must be able to name itself"


def test_an_existing_key_is_never_regenerated():
    """Regenerating would change the node's identity on restart, and every
    peer that pinned it, addressed INTERCOM to it, or mapped it would be
    talking to a stranger."""
    ident = _identity(public_key="-----BEGIN PUBLIC KEY-----\nORIGINAL\n-----END PUBLIC KEY-----")

    _service(ident)

    ident.create_keys.assert_not_called()
    ident.save.assert_not_called()
    assert "ORIGINAL" in ident.public_key


def test_the_generated_key_is_what_the_protocol_announces():
    """The whole point of the key: it becomes _node_id, which is the `peer` of
    every responsive PING and the hop identity for loop detection."""
    ident = _identity(public_key=None)

    _service(ident)
    protocol = HiveMindListenerProtocol(identity=ident, agent_protocol=MagicMock(), db=MagicMock())

    assert protocol._node_id == ident.public_key
    assert protocol._node_id, "an anonymous node cannot be put on a hive map"


def test_a_config_dir_we_cannot_write_does_not_stop_the_node():
    """A read-only or root-owned config dir is a normal container shape. The
    node served clients yesterday without a key; it must not refuse to boot
    today over one it can live without."""
    ident = _identity(public_key=None)
    ident.create_keys.side_effect = PermissionError("read-only config dir")

    service = _service(ident)

    assert service is not None, "an unwritable config dir must not kill the boot"
    assert not ident.public_key


def test_the_status_hooks_exist_before_the_key_is_generated():
    """Ordering is load-bearing: a failure raised before ProcessStatus is built
    reaches no error hook, so the supervisor sees the process die silently."""
    ident = _identity(public_key=None)
    order = []
    ident.create_keys.side_effect = lambda: order.append("create_keys")

    with patch("hivemind_core.service.ProcessStatus") as status:
        status.side_effect = lambda *a, **k: order.append("status") or MagicMock()
        with patch("hivemind_core.service.ClientDatabase", MagicMock()):
            HiveMindService(identity=ident, db=MagicMock())

    assert order.index("status") < order.index("create_keys"), order


def test_a_relay_reaches_its_master_with_the_same_identity_it_serves_with():
    """One node, one keypair, both directions. A separate upstream identity
    made a relay two nodes to the mesh: anonymous as a client of its master,
    keyed as a server to its own clients, with no way to see they were one."""
    from hivemind_core import service

    ident = _identity(public_key=None)
    built = {}

    class _Client:
        def __init__(self, **kwargs):
            built.update(kwargs)
            self.identity = kwargs.get("identity")

        def connect(self, *a, **kw):
            pass

        def close(self):
            pass

    svc = _service(ident)
    with patch.object(service, "HiveMessageBusClient", _Client), \
            patch.object(service, "HiveMindSlaveProtocol", MagicMock()), \
            patch.object(service, "create_daemon", lambda *a, **k: None), \
            patch.object(service, "upstream_config", lambda _cfg: {
                "enabled": True, "host": "10.0.0.1", "port": 5678,
                "key": "k", "password": "p", "ssl": False, "self_signed": True}), \
            patch.object(service, "own_listener_for", lambda *a, **k: None), \
            patch.object(service, "get_server_config", lambda: {"network_protocol": {}}):
        svc._connect_upstream(MagicMock())

    assert built.get("identity") is ident, \
        "the upstream link must use the node's own identity, not a second one"


def test_the_service_has_no_second_identity_file():
    from hivemind_core import service

    assert not hasattr(service, "upstream_identity"), \
        "a node has one identity"


def test_a_configured_private_key_is_kept(tmp_path):
    """A private key in the config is the node's identity even when the JSON
    carries no public_key. Generating a new pair would orphan the operator's
    key and rotate the identity that peers pinned and address INTERCOM to."""
    from json_database import JsonStorageXDG
    from poorman_handshake.asymmetric.utils import create_RSA_key, export_RSA_key

    from hivemind_bus_client.identity import NodeIdentity
    from hivemind_core.service import _ensure_node_identity

    _pub, secret = create_RSA_key()
    key_path = str(tmp_path / "operator.pem")
    export_RSA_key(secret, key_path)

    store = JsonStorageXDG("_identity", subfolder="hivemind")
    store.clear()  # it loaded the real user identity before the path override
    store["name"] = "operator-node"  # an EMPTY store is falsy and falls back
    store.path = str(tmp_path / "_identity.json")
    identity = NodeIdentity(identity_file=store)
    identity.private_key = key_path

    _ensure_node_identity(identity)

    assert identity.private_key == key_path, "the configured key must survive"

    # the property: what is published is the public half of the key ON DISK,
    # compared as key material rather than as an encoding
    from Cryptodome.PublicKey import RSA
    on_disk = RSA.import_key(open(key_path).read())
    assert RSA.import_key(identity.public_key).n == on_disk.n, \
        "the published key must be the public half of the key in use"
