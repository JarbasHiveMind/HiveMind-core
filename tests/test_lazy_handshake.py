from unittest.mock import MagicMock, patch

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_core.protocol import HiveMindClientConnection, HiveMindListenerProtocol


class FakeHandshake:
    created = 0

    def __init__(self, private_key=None):
        type(self).created += 1
        self.private_key = private_key
        self.pubkey = "server-pubkey"
        self.secret = b"derived-session-key"

    def generate_handshake(self, pubkey):
        self.client_pubkey = pubkey
        return "server-envelope"


def _protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.callbacks = MagicMock()
    agent.get_bus.return_value = agent.bus
    proto = HiveMindListenerProtocol(
        agent_protocol=agent,
        db=MagicMock(),
        require_crypto=False,
        handshake_enabled=True,
        policy_chain=MagicMock(),
    )
    proto.identity.private_key = "server-key"
    return proto


def _allow_legacy_config():
    return {"min_protocol_version": 0, "binarize": False}


def _client(proto, **kwargs):
    return HiveMindClientConnection(
        key="access-key",
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        hm_protocol=proto,
        **kwargs,
    )


def _sent_message(client, index):
    payload = client.send_msg.call_args_list[index].args[0]
    return HiveMessage.deserialize(payload)


def test_preshared_crypto_client_does_not_build_rsa_on_connect():
    proto = _protocol()
    client = _client(proto, crypto_key="0123456789abcdef")

    with patch("hivemind_core.protocol.HandShake", FakeHandshake):
        with patch("hivemind_core.protocol.get_server_config",
                   return_value=_allow_legacy_config()):
            FakeHandshake.created = 0
            proto.handle_new_client(client)

    assert FakeHandshake.created == 0
    hello = _sent_message(client, 0)
    handshake = _sent_message(client, 1)
    assert hello.msg_type == HiveMessageType.HELLO
    assert hello.payload["pubkey"] is None
    assert handshake.msg_type == HiveMessageType.HANDSHAKE
    assert handshake.payload["handshake"] is False
    assert handshake.payload["preshared_key"] is True


def test_rsa_fallback_builds_handshake_only_when_needed():
    proto = _protocol()
    client = _client(proto)

    with patch("hivemind_core.protocol.HandShake", FakeHandshake):
        with patch("hivemind_core.protocol.get_server_config",
                   return_value=_allow_legacy_config()):
            FakeHandshake.created = 0
            proto.handle_new_client(client)

    assert FakeHandshake.created == 1
    assert client.handshake is not None
    hello = _sent_message(client, 0)
    handshake = _sent_message(client, 1)
    assert hello.payload["pubkey"] == "server-pubkey"
    assert handshake.payload["handshake"] is True
    assert handshake.payload["preshared_key"] is False


def test_incoming_rsa_handshake_creates_legacy_handshake_lazily():
    proto = _protocol()
    client = _client(proto)
    msg = MagicMock()
    msg.payload = {
        "pubkey": "client-pubkey",
        "encodings": [],
        "ciphers": [],
    }

    with patch("hivemind_core.protocol.HandShake", FakeHandshake):
        FakeHandshake.created = 0
        proto.handle_handshake_message(msg, client)

    assert FakeHandshake.created == 1
    assert client.crypto_key == b"derived-session-key"
    assert client.handshake.client_pubkey == "client-pubkey"
