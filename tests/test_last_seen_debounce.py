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
        policy_chain=MagicMock(),
    )


def _client(peer="peer", key="access-key"):
    return SimpleNamespace(
        disconnect=MagicMock(),
        key=key,
        peer=peer,
        is_admin=False,
        layer1_session_id="nonce:a-session",
        sess=SimpleNamespace(session_id="a-session",
                             serialize=MagicMock(return_value={})),
    )


def test_last_seen_updates_are_debounced_per_client_key():
    user = SimpleNamespace(last_seen=0)
    db = FakeClientDatabase(user)
    proto = _protocol(db)
    proto.last_seen_update_interval = 30

    with (
        patch("hivemind_core.protocol.time.monotonic", side_effect=[100.0, 105.0, 131.0]),
        patch("hivemind_core.protocol.time.time", side_effect=[1000.0, 1031.0]),
    ):
        proto.update_last_seen(_client())
        proto.update_last_seen(_client())
        proto.update_last_seen(_client())

    assert db.lookups == 2
    assert db.updates == 2
    assert user.last_seen == 1031.0


def test_zero_last_seen_interval_preserves_per_message_updates():
    user = SimpleNamespace(last_seen=0)
    db = FakeClientDatabase(user)
    proto = _protocol(db)
    proto.last_seen_update_interval = 0

    with (
        patch("hivemind_core.protocol.time.monotonic") as monotonic,
        patch("hivemind_core.protocol.time.time", side_effect=[100.0, 101.0]),
    ):
        proto.update_last_seen(_client())
        proto.update_last_seen(_client())

    assert db.lookups == 2
    assert db.updates == 2
    assert user.last_seen == 101.0
    monotonic.assert_not_called()


def test_default_config_throttles_last_seen_writes():
    user = SimpleNamespace(last_seen=0)
    db = FakeClientDatabase(user)
    proto = _protocol(db)

    with (
        patch("hivemind_core.protocol.time.monotonic", side_effect=[100.0, 101.0]),
        patch("hivemind_core.protocol.time.time", side_effect=[1000.0]),
    ):
        proto.update_last_seen(_client())
        proto.update_last_seen(_client())

    assert db.updates == 1
    assert user.last_seen == 1000.0


def test_disconnect_keeps_debounce_cache_for_shared_key_sibling():
    proto = _protocol(FakeClientDatabase(SimpleNamespace(last_seen=0)))
    disconnected = _client(peer="peer-1")
    sibling = _client(peer="peer-2")
    proto.clients = {
        disconnected.peer: disconnected,
        sibling.peer: sibling,
    }
    proto._last_seen_updates["access-key"] = 100.0

    proto.handle_client_disconnected(disconnected)

    assert disconnected.peer not in proto.clients
    assert sibling.peer in proto.clients
    assert proto._last_seen_updates["access-key"] == 100.0
    disconnected.disconnect.assert_called_once_with()


def test_disconnect_clears_debounce_cache_after_last_key_peer_leaves():
    proto = _protocol(FakeClientDatabase(SimpleNamespace(last_seen=0)))
    disconnected = _client(peer="peer-1")
    other_key = _client(peer="peer-2", key="other-key")
    proto.clients = {
        disconnected.peer: disconnected,
        other_key.peer: other_key,
    }
    proto._last_seen_updates["access-key"] = 100.0
    proto._last_seen_updates["other-key"] = 101.0

    proto.handle_client_disconnected(disconnected)

    assert "access-key" not in proto._last_seen_updates
    assert proto._last_seen_updates["other-key"] == 101.0
