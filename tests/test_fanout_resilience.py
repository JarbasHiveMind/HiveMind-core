"""Regression tests for the fan-out hot path in
``HiveMindListenerProtocol.handle_broadcast_message``.

Before this fix, a single peer raising out of ``HiveMindClientConnection.send``
(e.g. a ``binarize=True`` client whose metadata exceeds the WIRE-1 binary cap,
or a peer in a broken crypto state) escaped the fan-out loop and every peer
ordered after it in ``self.clients`` never received the message. One bad
client silenced a broadcast to the whole mesh.

It also checks the message is serialized once per fan-out, not once per peer:
``HiveMessage.serialize()`` re-runs ``json.dumps``/``json.loads`` and route
filtering on every call, so doing it per peer wastes 10-40ms across a
1000-peer fan-out for no reason -- the plaintext does not depend on the peer.
"""
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindListenerProtocol


def _make_protocol():
    proto = object.__new__(HiveMindListenerProtocol)
    proto.peer = "master:0.0.0.0"
    proto.identity = MagicMock(public_key="pubkey-master", site_id=None)
    proto.clients = {}
    proto.illegal_callback = MagicMock()
    proto.broadcast_callback = MagicMock()
    return proto


def _make_admin_client(peer: str) -> MagicMock:
    client = MagicMock()
    client.peer = peer
    client.is_admin = True
    client.can_broadcast = True
    return client


def _broadcast() -> HiveMessage:
    inner = HiveMessage(HiveMessageType.BUS,
                        payload=Message("speak", {"utterance": "hi"}))
    return HiveMessage(HiveMessageType.BROADCAST, payload=inner)


def test_one_raising_peer_does_not_block_delivery_to_others():
    proto = _make_protocol()
    originator = _make_admin_client("origin::0")
    bad = _make_admin_client("bad::1")
    bad.send.side_effect = ValueError("metadata exceeds WIRE-1 binary cap")
    good_before = _make_admin_client("good-before::2")
    good_after = _make_admin_client("good-after::3")

    proto.clients = {
        originator.peer: originator,
        good_before.peer: good_before,
        bad.peer: bad,
        good_after.peer: good_after,
    }

    proto.handle_broadcast_message(_broadcast(), originator)

    good_before.send.assert_called_once()
    good_after.send.assert_called_once()
    bad.send.assert_called_once()


def test_fanout_serializes_once_not_once_per_peer():
    proto = _make_protocol()
    originator = _make_admin_client("origin::0")
    peers = [_make_admin_client(f"peer::{i}") for i in range(5)]
    proto.clients = {originator.peer: originator,
                     **{p.peer: p for p in peers}}

    with patch.object(HiveMessage, "serialize",
                      wraps=HiveMessage.serialize, autospec=True) as spy:
        proto.handle_broadcast_message(_broadcast(), originator)

    assert spy.call_count == 1, \
        f"expected message.serialize() once per fan-out, called {spy.call_count} times"

    for p in peers:
        p.send.assert_called_once()
        args, _ = p.send.call_args
        assert len(args) == 2 and isinstance(args[1], str), \
            "each peer must receive the shared pre-serialized plaintext"
