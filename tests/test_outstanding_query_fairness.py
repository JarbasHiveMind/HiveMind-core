"""Fairness of the outstanding-query eviction (HIVEMIND-MSG-1 §5.2).

``_record_outstanding_query`` binds a client-supplied ``query_id`` to the
server-observed peer that sent the request, and bounds that store with a hard
cap (``OUTSTANDING_QUERY_MAX``). Because ``query_id`` is chosen by the client,
any single permitted peer (``can_escalate``/``can_propagate`` default true)
can mint an unbounded number of distinct ids. If eviction picked the globally
oldest entry regardless of who owns it, one peer flooding the store could
evict every other peer's legitimately-outstanding return path, causing their
genuine answers to be dropped by ``_route_query_response`` as "no request
seen" — a cross-peer answer-loss denial of service.

Eviction must instead prefer the INSERTING peer's own oldest entry, so a
flood can only ever cost the flooder its own bindings.
"""
from hivemind_core.protocol import (HiveMindListenerProtocol,
                                     OUTSTANDING_QUERY_MAX)


def _make_node() -> HiveMindListenerProtocol:
    node = object.__new__(HiveMindListenerProtocol)
    node._outstanding_queries_store = None
    node._outstanding_query_lock = None
    return node


def test_flood_does_not_evict_other_peers_entry():
    """A flood of distinct query_ids from one peer must never evict a
    different peer's outstanding query."""
    node = _make_node()

    node._record_outstanding_query("victim-qid", "victim-peer:1")
    for i in range(OUTSTANDING_QUERY_MAX):
        node._record_outstanding_query(f"atk-{i}", "attacker-peer:2")

    assert node._outstanding_return_path("victim-qid") == "victim-peer:1"


def test_flooding_peer_self_caps():
    """The flooder's own entries are what gets evicted to make room, so it
    never holds more than MAX - 1 of its own bindings once another peer's
    entry is present."""
    node = _make_node()

    node._record_outstanding_query("victim-qid", "victim-peer:1")
    for i in range(OUTSTANDING_QUERY_MAX):
        node._record_outstanding_query(f"atk-{i}", "attacker-peer:2")

    store = node._outstanding_queries
    attacker_entries = sum(1 for (peer, _) in store.values()
                            if peer == "attacker-peer:2")
    assert attacker_entries <= OUTSTANDING_QUERY_MAX - 1
    assert len(store) == OUTSTANDING_QUERY_MAX


def test_newcomers_still_admitted_after_flood():
    """Once an attacker has filled the store, fresh peers recording a single
    query each must still be admitted (displacing the global-oldest attacker
    entries), and the store never exceeds the cap."""
    node = _make_node()

    for i in range(OUTSTANDING_QUERY_MAX):
        node._record_outstanding_query(f"atk-{i}", "attacker-peer:2")

    fresh_qids = [f"fresh-qid-{i}" for i in range(5)]
    for i, qid in enumerate(fresh_qids):
        node._record_outstanding_query(qid, f"fresh-peer:{i}")

    for qid in fresh_qids:
        assert node._outstanding_return_path(qid) is not None
    assert len(node._outstanding_queries) == OUTSTANDING_QUERY_MAX


def test_first_writer_wins():
    """A query_id already bound is never rebound to a different peer."""
    node = _make_node()

    node._record_outstanding_query("qid-1", "peer-a:1")
    node._record_outstanding_query("qid-1", "peer-b:2")

    assert node._outstanding_return_path("qid-1") == "peer-a:1"
