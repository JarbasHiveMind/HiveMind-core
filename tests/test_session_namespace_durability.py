"""Durable, identity-scoped Layer-1 session namespace (HIVEMIND-BRIDGE-1 §4).

A non-admin's declared session_id is NATted at the inbound boundary to
``f"{namespace}:{declared_id}"``. If that namespace were the per-connection
``conn_nonce`` (reminted on every reconnect), a satellite that dropped and
reconnected would land in a different Layer-1 session, and a message replayed
by the scheduler carrying the pre-drop session_id would become undeliverable.

``HiveMindClientConnection.session_namespace`` fixes this: the namespace is
derived from the DURABLE DB identity (client_id) plus the hub's persistent
node public key, so it survives a reconnect (new nonce, same client_id) and a
hub restart (the salt is the persistent node identity). The token IDENTIFIES,
it does not AUTHENTICATE — it is derived from the durable identity, never the
secret access key, and hub-salted so it is not linkable across hubs.
"""
from unittest.mock import MagicMock

from ovos_bus_client.session import Session

from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.get_bus.return_value = agent.bus

    db = MagicMock()

    return HiveMindListenerProtocol(agent_protocol=agent, db=db)


def _make_client(client_id, key="access-key", public_key="hub-pubkey-A",
                 db=True):
    proto = _make_protocol()
    client = HiveMindClientConnection(
        key=key,
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=proto,
        sess=Session(session_id="default"),
    )
    # Stub the hub salt to a known value AFTER __post_init__ (which reads the
    # real RSA key via identity_rsa_key); session_namespace reads only
    # identity.public_key.
    proto.identity.public_key = public_key
    if db:
        user = MagicMock()
        user.client_id = client_id
        proto.db.get_client_by_api_key.return_value = user
    else:
        # unauthenticated/edge: no reachable DB -> fallback to conn_nonce
        proto.db = None
    return client


def test_session_namespace_survives_reconnect():
    # A client with a stable DB client_id keeps the SAME namespace across a
    # reconnect, even though conn_nonce is reminted. THIS IS THE FAIL-BEFORE
    # CASE: with conn_nonce as the namespace, the two ids below would differ.
    client = _make_client(client_id=42)
    before = client.session_namespace
    id_before = HiveMindListenerProtocol._layer1_session_id(
        client, is_admin=False, declared_id="chat")

    # simulate a reconnect: force a brand-new conn_nonce, same identity
    old_nonce = client.conn_nonce
    client._conn_nonce = ""
    client.invalidate_user()
    assert client.conn_nonce != old_nonce

    after = client.session_namespace
    id_after = HiveMindListenerProtocol._layer1_session_id(
        client, is_admin=False, declared_id="chat")

    assert before == after
    assert id_before == id_after == f"{before}:chat"


def test_distinct_identities_get_distinct_namespaces():
    a = _make_client(client_id=1)
    b = _make_client(client_id=2)
    assert a.session_namespace != b.session_namespace


def test_namespace_is_not_the_secret_key():
    # The token must be derived from the durable identity, not the secret
    # access key: changing the key (same client_id + salt) does not change
    # the namespace, and the raw key never appears in the token.
    base = _make_client(client_id=7, key="secret-one")
    rotated = _make_client(client_id=7, key="secret-two")
    assert base.session_namespace == rotated.session_namespace
    assert "secret-one" not in base.session_namespace
    assert "secret-two" not in rotated.session_namespace


def test_namespace_is_hub_salted_and_stable():
    # Same client_id + same hub salt -> same token across two separate
    # connection objects; a different hub salt -> different token (a session
    # is not linkable across hubs).
    same_hub_1 = _make_client(client_id=9, public_key="hub-A")
    same_hub_2 = _make_client(client_id=9, public_key="hub-A")
    other_hub = _make_client(client_id=9, public_key="hub-B")

    assert same_hub_1.session_namespace == same_hub_2.session_namespace
    assert same_hub_1.session_namespace != other_hub.session_namespace


def test_admin_branch_unchanged():
    client = _make_client(client_id=5)
    sid = HiveMindListenerProtocol._layer1_session_id(
        client, is_admin=True, declared_id="default")
    assert sid == "default"


def test_fallback_to_conn_nonce_without_db():
    # An unauthenticated/edge client with no DB falls back to conn_nonce
    # instead of crashing.
    client = _make_client(client_id=None, db=False)
    assert client.session_namespace == client.conn_nonce
    sid = HiveMindListenerProtocol._layer1_session_id(
        client, is_admin=False, declared_id="x")
    assert sid == f"{client.conn_nonce}:x"
