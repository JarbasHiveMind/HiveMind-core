"""Two more places where ``self.clients`` was read without a snapshot.

``self.clients`` is mutated on the tornado IOLoop thread while other threads
read it. An exception raised out of a read escapes ``on_message`` or
``on_close``, and tornado then tears down a websocket that did nothing wrong.

The fan-out loops were fixed earlier; these two were not:

* ``_route_query_response`` gated a CASCADE on ``originator_peer in
  self.clients`` and then indexed ``self.clients[originator_peer]``. A
  disconnect between the two raised ``KeyError``, which the surrounding
  ``except ConnectionError`` did not catch, and the *responder* lost its
  connection.
* ``handle_client_disconnected`` iterated ``self.clients.values()`` live while
  a reconnect could insert, raising ``RuntimeError`` out of ``on_close``.
"""
import sys
import threading
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindListenerProtocol

ORIGINATOR = "sat-originator"


def _node() -> HiveMindListenerProtocol:
    node = object.__new__(HiveMindListenerProtocol)
    node.peer = "master:0.0.0.0"
    node.identity = MagicMock(public_key="pubkey-master", site_id=None)
    node.clients = {}
    node._pending_cascades = {}
    node._upstream_hm = None
    node.cascade_select_callback = None
    return node


def _cascade_response(query_id: str) -> HiveMessage:
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("speak", {"utterance": "hi"}))
    return HiveMessage(HiveMessageType.CASCADE, payload=inner,
                       metadata={"originator_peer": ORIGINATOR,
                                 "query_id": query_id})


def _responder() -> MagicMock:
    responder = MagicMock()
    responder.peer = "sat-responder"
    return responder


class DisconnectOnLookup(dict):
    """Client table where the peer disconnects the instant it is looked up.

    This pins the interleaving down instead of racing for it: the window
    between a membership test and an index is one bytecode wide, so a
    threaded test hits it only by luck. Reading the table twice is the bug,
    whether or not a scheduler obliges.
    """

    def __contains__(self, peer):
        found = dict.__contains__(self, peer)
        self.pop(peer, None)
        return found

    def get(self, peer, default=None):
        conn = dict.get(self, peer, default)
        self.pop(peer, None)
        return conn


def test_cascade_response_survives_the_originator_disconnecting():
    """The originator vanishing must not take the responder down with it.

    A ``KeyError`` here is not caught by the ``except ConnectionError`` around
    ``get_bus``; it escapes to tornado's ``on_message`` and closes the
    *responder's* websocket. Only ``cascade_select_callback`` reaches this
    gate, which is why the plain-routing tests never covered it.
    """
    node = _node()
    node.clients = DisconnectOnLookup()
    node.cascade_select_callback = MagicMock(return_value=None)
    node.get_bus = MagicMock(return_value=MagicMock())
    responder = _responder()

    originator = MagicMock()
    originator.peer = ORIGINATOR
    node.clients[ORIGINATOR] = originator

    node._route_query_response(_cascade_response("q1"), responder)

    assert responder.disconnect.call_count == 0


def test_disconnect_survives_a_concurrent_reconnect():
    """``handle_client_disconnected`` reads the client table on the way out."""
    node = _node()
    node.callbacks = MagicMock()
    node.binary_data_protocol = MagicMock()
    node.agent_protocol = MagicMock()
    node._last_seen_updates = {}
    node._emit_lifecycle = MagicMock()

    # a long client table makes the un-snapshotted `any()` below spend enough
    # bytecodes iterating for a concurrent insert to land inside it
    for i in range(300):
        stable = MagicMock()
        stable.peer = f"sat-stable-{i}"
        stable.key = f"key-stable-{i}"
        node.clients[stable.peer] = stable

    stop = threading.Event()

    def reconnect_storm(mutator_id):
        peer = f"sat-reconnecting-{mutator_id}"
        while not stop.is_set():
            node.clients.pop(peer, None)
            conn = MagicMock()
            conn.peer = peer
            conn.key = f"key-{mutator_id}"
            node.clients[peer] = conn

    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    threads = [threading.Thread(target=reconnect_storm, args=(i,), daemon=True)
               for i in range(8)]
    for t in threads:
        t.start()
    try:
        for i in range(600):
            leaving = MagicMock()
            leaving.peer = f"sat-leaving-{i}"
            leaving.key = "key-leaving"
            leaving.is_admin = True
            leaving.sess.session_id = f"sess-{i}"
            node.clients[leaving.peer] = leaving
            # a raise here escapes to tornado's on_close
            node.handle_client_disconnected(leaving)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=5)
        sys.setswitchinterval(old_interval)
