"""Per-connection, identity-scoped Layer-1 session namespace (BRIDGE-1 §4).

A non-admin's declared session_id is NATted at the inbound boundary to
``f"{namespace}:{declared_id}"``.

THIS FILE SHIPPED WITH #299 ASSERTING THAT THE NAMESPACE SURVIVES A RECONNECT,
and T-6696 measured that as the defect rather than the feature. Keyed on the
durable DB row alone, two LIVE connections sharing one access key resolved the
same declared name to the same Layer-1 session, so the orchestrator merged two
devices into one conversation. BRIDGE-1 §4 requires the opposite: the id is
derived from "the connection's own identity (§3), which the server already
guarantees distinct", and "two connections that named the same session thus
never resolve to the same Layer-1 identity".

The durability goal is not merely outweighed. AGENT-1 §3.3 forbids selecting a
receiver "by a shared session namespace", which is the mechanism a
cross-connection namespace provides, so a response for a session whose
connection is gone is logged and dropped rather than delivered.

What this file still pins, and what it now pins in the other direction:

- KEPT: the token IDENTIFIES and does not AUTHENTICATE. It is derived from the
  durable identity and NEVER from the secret access key, and it is node-salted
  so a session is not linkable across hubs. Both are still true and both are
  still tested, on ONE connection rather than across two, because two
  connections are now required to differ.
- INVERTED: the reconnect cell. It asserted the ids match; it now asserts they
  differ, with the reason.
"""
import threading
import uuid
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


def _make_client(client_id, key="access-key", public_key="node-pubkey-A",
                 db=True):
    proto = _make_protocol()
    client = HiveMindClientConnection(
        key=key,
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=proto,
        sess=Session(session_id="default"),
    )
    # Stub the node salt to a known value AFTER __post_init__ (which reads the
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


def test_session_namespace_does_not_survive_a_reconnect():
    # INVERTED BY T-6696. This cell asserted the ids MATCH across a reconnect,
    # which is the property that merged two live connections onto one Layer-1
    # session. BRIDGE-1 §4 requires per-connection derivation, and AGENT-1 §3.3
    # forbids delivering to a peer selected by a shared session namespace, so a
    # response for a gone connection is logged and dropped rather than routed
    # to whoever now holds that name.
    client = _make_client(client_id=42)
    before = client.session_namespace
    id_before = HiveMindListenerProtocol._layer1_session_id(
        client, is_admin=False, declared_id="chat")

    # simulate a reconnect: force a brand-new conn_nonce, same identity. The
    # nonce is minted when the connection object is constructed, so a reconnect
    # is modelled by replacing it, not by clearing it and reading it again.
    old_nonce = client.conn_nonce
    client._conn_nonce = uuid.uuid4().hex
    client.invalidate_user()
    assert client.conn_nonce != old_nonce

    after = client.session_namespace
    id_after = HiveMindListenerProtocol._layer1_session_id(
        client, is_admin=False, declared_id="chat")

    assert before != after, (
        "a namespace that survives a reconnect is shared between connections, "
        "which is what BRIDGE-1 §4 forbids")
    assert id_before != id_after
    assert id_after == f"{after}:chat"


def test_distinct_identities_get_distinct_namespaces():
    a = _make_client(client_id=1)
    b = _make_client(client_id=2)
    assert a.session_namespace != b.session_namespace


def test_namespace_is_not_the_secret_key():
    # UNCHANGED PROPERTY, measured differently. The token must be derived from
    # the durable identity and not from the secret access key. Two SEPARATE
    # connections now differ by construction, so key-independence is measured on
    # ONE connection whose key rotates under it, which is the case that matters:
    # a rotated key must not move a live connection's sessions.
    client = _make_client(client_id=7, key="secret-one")
    before = client.session_namespace
    client.key = "secret-two"
    client.invalidate_user()
    after = client.session_namespace

    assert before == after
    assert "secret-one" not in before
    assert "secret-two" not in after


def test_namespace_is_node_salted():
    # UNCHANGED PROPERTY, measured differently, and the "and_stable" half of the
    # old name is gone with the durability it named. A session must not be
    # linkable across hubs: the same client on a different node salt gets a
    # different token. Measured on ONE connection with the salt moved under it,
    # because two connections now differ whatever the salt is.
    client = _make_client(client_id=9, public_key="node-A")
    on_node_a = client.session_namespace

    client.hm_protocol.identity.public_key = "node-B"
    client.invalidate_user()
    on_node_b = client.session_namespace

    assert on_node_a != on_node_b


def test_two_connections_on_one_identity_never_share_a_namespace():
    # The property #299 removed, restored here at the level this file works at.
    # The end-to-end form is in
    # tests/test_one_key_two_connections_do_not_share_a_session.py.
    a = _make_client(client_id=9, public_key="node-A")
    b = _make_client(client_id=9, public_key="node-A")
    assert a.session_namespace != b.session_namespace


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


def test_namespace_is_scoped_to_the_durable_client_row():
    # The durable ``client_id`` is a TERM OF THE HASH, not decoration. Without
    # this cell the whole ``resolve_user`` block can be dropped from the
    # derivation and the suite stays green, which makes the token merely
    # per-connection instead of per-connection AND identity-scoped.
    client = _make_client(client_id=11)
    before = client.session_namespace

    # same connection, same nonce, same salt: only the row moves
    assert client.conn_nonce == client.conn_nonce
    nonce = client.conn_nonce
    user = MagicMock()
    user.client_id = 12
    client.hm_protocol.db.get_client_by_api_key.return_value = user
    client.invalidate_user()
    after = client.session_namespace

    assert client.conn_nonce == nonce
    assert before != after, (
        "the durable client_id must be in the hash: the token is "
        "identity-scoped, not only per connection")
    assert nonce not in (before, after)


def test_conn_nonce_is_minted_before_any_read():
    # The DETERMINISTIC half of the no-split guard. A lazy mint is a race, and a
    # race cell catches it only sometimes; this cell catches it every run: the
    # private field already holds the nonce before anything reads the property,
    # so there is no first-read to race.
    client = _make_client(client_id=13)
    assert client._conn_nonce, (
        "the nonce must be minted when the connection object is constructed; "
        "a lazy mint has no lock and two threads both mint")
    assert client._conn_nonce == client.conn_nonce


def test_conn_nonce_does_not_split_under_concurrent_first_reads():
    # ``session_namespace`` is read on every inbound and every outbound bus
    # message, and three threads send on one connection, so a nonce minted
    # lazily without a lock lets two threads mint and the last write win. That
    # splits one connection's messages across two Layer-1 sessions and makes
    # the outbound un-NAT miss its own prefix. The nonce is therefore minted
    # when the connection object is constructed.
    #
    # This cell is a RACE DETECTOR, so it reds on a lazy mint only in some runs
    # (measured 2 of 6 against that mutant). The deterministic guard is
    # ``test_conn_nonce_is_minted_before_any_read`` above; this one states the
    # consequence the reader needs to see.
    client = _make_client(client_id=13)
    seen = []
    lock = threading.Lock()
    start = threading.Barrier(8)

    def read():
        start.wait()
        value = client.conn_nonce
        with lock:
            seen.append(value)

    threads = [threading.Thread(target=read) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(seen)) == 1, f"one connection minted several nonces: {set(seen)}"
    assert client.session_namespace == client.session_namespace
