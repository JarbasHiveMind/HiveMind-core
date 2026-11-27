"""Regression test for a reproduced concurrency bug in fan-out.

``self.clients`` is a plain dict, mutated on the tornado IOLoop thread
(connect/reconnect/disconnect) while fan-out on other threads (the OVOS bus
thread, the upstream slave thread) iterated it directly. With ~30 satellites
plus one reconnecting, that raced into
``RuntimeError: dictionary changed size during iteration``. The exception
escaped ``on_message``, so tornado tore down the *sender's* websocket -- one
satellite got disconnected because a different satellite reconnected, and the
broadcast only reached some peers.

Fan-out now iterates a ``list(self.clients.values())`` snapshot, so a
concurrent mutation can no longer raise mid-iteration.
"""
import sys
import threading
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindListenerProtocol

DEFAULT_PEER = "master:0.0.0.0"
NUM_SATELLITES = 30


def _make_node() -> HiveMindListenerProtocol:
    node = object.__new__(HiveMindListenerProtocol)
    node.peer = DEFAULT_PEER
    node.identity = MagicMock(public_key="pubkey-master", site_id=None)
    node.clients = {}
    node.illegal_callback = None
    node.broadcast_callback = None
    return node


def _make_client(peer: str) -> MagicMock:
    client = MagicMock()
    client.peer = peer
    client.is_admin = True
    client.can_broadcast = True
    return client


def _broadcast() -> HiveMessage:
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("speak", {"utterance": "hi"}))
    return HiveMessage(HiveMessageType.BROADCAST, payload=inner)


def test_fan_out_survives_concurrent_client_mutation():
    node = _make_node()
    sent = {}
    for i in range(NUM_SATELLITES):
        peer = f"sat-{i}"
        conn = MagicMock()
        conn.peer = peer
        # send() takes an optional pre-serialized plaintext from the fan-out
        # caller; swallow it here so the stub keeps recording just the message.
        conn.send = lambda m, _plaintext=None, box=sent.setdefault(peer, []): box.append(m)
        node.clients[peer] = conn
    pre_existing_peers = set(node.clients)

    sender = _make_client("sat-sender")
    node.clients[sender.peer] = sender

    stop = threading.Event()

    def reconnect_storm(mutator_id):
        # other satellites reconnecting: pop + re-add an entry in a tight
        # loop, racing the fan-out below on this thread while it iterates
        # on the main thread
        while not stop.is_set():
            peer = f"sat-reconnecting-{mutator_id}"
            node.clients.pop(peer, None)
            conn = MagicMock()
            conn.peer = peer
            conn.send = lambda m, _plaintext=None: None
            node.clients[peer] = conn

    # lower the GIL switch interval so the mutator threads interleave with
    # the fan-out loop far more often, making the race reliable in a test
    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    threads = [threading.Thread(target=reconnect_storm, args=(i,), daemon=True)
               for i in range(8)]
    for t in threads:
        t.start()
    try:
        for _ in range(2000):
            node.handle_broadcast_message(_broadcast(), sender)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=5)
        sys.setswitchinterval(old_interval)

    for peer in pre_existing_peers:
        assert sent[peer], f"{peer} never received the broadcast"
