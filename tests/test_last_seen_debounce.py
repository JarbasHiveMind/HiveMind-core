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


def _client():
    return SimpleNamespace(key="access-key", peer="peer")


def test_last_seen_updates_are_debounced_per_client_key():
    user = SimpleNamespace(last_seen=0)
    db = FakeClientDatabase(user)
    proto = _protocol(db)
    proto.last_seen_update_interval = 30

    with patch("hivemind_core.protocol.time.time", side_effect=[100.0, 105.0, 131.0]):
        proto.update_last_seen(_client())
        proto.update_last_seen(_client())
        proto.update_last_seen(_client())

    assert db.lookups == 2
    assert db.updates == 2
    assert user.last_seen == 131.0


def test_zero_last_seen_interval_preserves_per_message_updates():
    user = SimpleNamespace(last_seen=0)
    db = FakeClientDatabase(user)
    proto = _protocol(db)
    proto.last_seen_update_interval = 0

    with patch("hivemind_core.protocol.time.time", side_effect=[100.0, 101.0]):
        proto.update_last_seen(_client())
        proto.update_last_seen(_client())

    assert db.lookups == 2
    assert db.updates == 2
    assert user.last_seen == 101.0
