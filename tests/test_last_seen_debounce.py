import queue
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from hivemind_core.protocol import HiveMindListenerProtocol


class FakeClientDatabase:
    def __init__(self, user):
        self.user = user
        self.lookups = 0
        self.updates = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get_client_by_api_key(self, key):
        self.lookups += 1
        if key == "access-key":
            return self.user
        return None

    def update_item(self, user):
        self.updates += 1
        self.user = user


def _protocol(db):
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.callbacks = MagicMock()
    agent.get_bus.return_value = agent.bus
    return HiveMindListenerProtocol(
        agent_protocol=agent,
        db=db,
        require_crypto=False,
        handshake_enabled=True,
        policy_chain=MagicMock(),
    )


def _client(peer="peer", key="access-key"):
    return SimpleNamespace(
        disconnect=MagicMock(),
        key=key,
        last_seen=-1,
        peer=peer,
        sess=SimpleNamespace(serialize=MagicMock(return_value={})),
    )


def test_last_seen_touches_are_queued_and_coalesced_per_client_key():
    user = SimpleNamespace(last_seen=0)
    db = FakeClientDatabase(user)
    proto = _protocol(db)
    proto.last_seen_update_interval = 30
    queued = []
    proto._last_seen_queue = MagicMock()
    proto._last_seen_queue.put_nowait.side_effect = queued.append
    client = _client()

    with (
        patch("hivemind_core.protocol.time.time", side_effect=[1000.0, 1005.0, 1031.0]),
        patch("hivemind_core.protocol.time.monotonic", side_effect=[100.0, 105.0, 131.0]),
    ):
        proto.touch_last_seen(client)
        proto.touch_last_seen(client)
        proto.touch_last_seen(client)

    assert queued == [(client, 1000.0), (client, 1031.0)]
    assert client.last_seen == 1031.0
    assert db.lookups == 0
    assert db.updates == 0


def test_zero_last_seen_interval_queues_every_message_without_database_io():
    user = SimpleNamespace(last_seen=0)
    db = FakeClientDatabase(user)
    proto = _protocol(db)
    proto.last_seen_update_interval = 0
    queued = []
    proto._last_seen_queue = MagicMock()
    proto._last_seen_queue.put_nowait.side_effect = queued.append
    client = _client()

    with (
        patch("hivemind_core.protocol.time.time", side_effect=[100.0, 101.0]),
        patch("hivemind_core.protocol.time.monotonic", side_effect=[10.0, 11.0]),
    ):
        proto.touch_last_seen(client)
        proto.touch_last_seen(client)

    assert queued == [(client, 100.0), (client, 101.0)]
    assert client.last_seen == 101.0
    assert db.lookups == 0
    assert db.updates == 0


def test_full_queue_reopens_coalescing_gate_for_retry():
    proto = _protocol(FakeClientDatabase(SimpleNamespace(last_seen=0)))
    proto.last_seen_update_interval = 30
    proto._last_seen_queue = MagicMock()
    proto._last_seen_queue.put_nowait.side_effect = queue.Full
    client = _client()

    with (
        patch("hivemind_core.protocol.time.time", return_value=100.0),
        patch("hivemind_core.protocol.time.monotonic", return_value=10.0),
    ):
        proto.touch_last_seen(client)

    assert client.key not in proto._last_seen_next_flush


def test_disconnect_keeps_debounce_cache_for_shared_key_sibling():
    proto = _protocol(FakeClientDatabase(SimpleNamespace(last_seen=0)))
    disconnected = _client(peer="peer-1")
    sibling = _client(peer="peer-2")
    proto.clients = {
        disconnected.peer: disconnected,
        sibling.peer: sibling,
    }
    proto._last_seen_next_flush["access-key"] = 100.0

    proto.handle_client_disconnected(disconnected)

    assert disconnected.peer not in proto.clients
    assert sibling.peer in proto.clients
    assert proto._last_seen_next_flush["access-key"] == 100.0
    disconnected.disconnect.assert_called_once_with()


def test_disconnect_clears_debounce_cache_after_last_key_peer_leaves():
    proto = _protocol(FakeClientDatabase(SimpleNamespace(last_seen=0)))
    disconnected = _client(peer="peer-1")
    other_key = _client(peer="peer-2", key="other-key")
    proto.clients = {
        disconnected.peer: disconnected,
        other_key.peer: other_key,
    }
    proto._last_seen_next_flush["access-key"] = 100.0
    proto._last_seen_next_flush["other-key"] = 101.0

    proto.handle_client_disconnected(disconnected)

    assert "access-key" not in proto._last_seen_next_flush
    assert proto._last_seen_next_flush["other-key"] == 101.0
