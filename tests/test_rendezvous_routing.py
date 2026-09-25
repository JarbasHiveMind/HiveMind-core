"""RENDEZVOUS routing — the mailbox hook and the mailbox-less default.

RENDEZVOUS was reserved in the enum in 2021 and fell through to the empty
handle_unknown_message stub ever since. These tests pin the two things that
routing has to get right: an ordinary node says so out loud, and a rendezvous
node serves the caller's own mailbox and no other.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindListenerProtocol


def _protocol(**kwargs):
    agent = MagicMock()
    agent.bus = MagicMock()
    agent.callbacks = MagicMock()
    agent.get_bus.return_value = agent.bus
    return HiveMindListenerProtocol(
        agent_protocol=agent,
        db=MagicMock(),
        policy_chain=MagicMock(),
        **kwargs,
    )


def _client(key="access-key", pub_key="CLIENT-PEM"):
    sent = []
    return SimpleNamespace(
        key=key,
        pub_key=pub_key,
        peer="peer::sess",
        send=sent.append,
        sent=sent,
    )


class _RecordingMailbox:
    """Stands in for hivemind_rendezvous.RendezvousMailbox."""

    def __init__(self):
        self.calls = []

    def handle(self, message, owner_pubkey):
        self.calls.append((message, owner_pubkey))
        return HiveMessage(HiveMessageType.RENDEZVOUS,
                           payload={"status": "ok", "messages": []})


def test_node_without_a_mailbox_says_so():
    # silence would be indistinguishable from "no mail waiting", and a peer
    # that cannot tell those apart cannot fail over to a real rendezvous node
    proto = _protocol()
    client = _client()
    proto.handle_rendezvous_message(
        HiveMessage(HiveMessageType.RENDEZVOUS, payload={"cmd": "collect"}),
        client)
    assert len(client.sent) == 1
    reply = client.sent[0]
    assert reply.msg_type == HiveMessageType.RENDEZVOUS
    assert reply.payload["status"] == "error"
    assert reply.payload["reason"] == "not_a_rendezvous_node"


def test_mailbox_is_served_the_authenticated_access_key():
    # the caller does not get to name a mailbox: whatever it puts in the
    # payload, the owner is the access key THIS connection authenticated with
    proto = _protocol()
    proto.mailbox = _RecordingMailbox()
    client = _client(key="my-key")

    proto.handle_rendezvous_message(
        HiveMessage(HiveMessageType.RENDEZVOUS,
                    payload={"cmd": "collect", "pubkey": "VICTIM-PEM",
                             "key": "victim-key"}),
        client)

    _msg, owner = proto.mailbox.calls[0]
    assert owner == "my-key"


def test_a_declared_pubkey_cannot_claim_a_mailbox():
    """The HELLO-declared pubkey carries no proof of possession.

    trusted_pubkeys is filled from the HELLO payload and keyed by the caller's
    OWN access key, so if ownership were derived from it, any admitted client
    could name a victim's public key — which is public by design, it is the
    INTERCOM addressing key — and be handed the victim's mailbox.
    """
    proto = _protocol()
    proto.mailbox = _RecordingMailbox()
    proto.trusted_pubkeys["attacker-key"] = "VICTIM-PEM"
    client = _client(key="attacker-key", pub_key="VICTIM-PEM")

    proto.handle_rendezvous_message(
        HiveMessage(HiveMessageType.RENDEZVOUS, payload={"cmd": "collect"}),
        client)

    _msg, owner = proto.mailbox.calls[0]
    assert owner == "attacker-key", "ownership must not come from a declared pubkey"


def test_a_connection_with_no_identity_gets_no_mailbox():
    # otherwise every such connection shares one mailbox
    proto = _protocol()
    proto.mailbox = _RecordingMailbox()
    client = _client(key="")

    proto.handle_rendezvous_message(
        HiveMessage(HiveMessageType.RENDEZVOUS, payload={"cmd": "collect"}),
        client)

    assert proto.mailbox.calls == []
    assert client.sent[0].payload["reason"] == "no_client_identity"


def test_a_raising_mailbox_does_not_kill_the_connection():
    class _Boom:
        def handle(self, message, owner):
            raise RuntimeError("backend down")

    proto = _protocol()
    proto.mailbox = _Boom()
    client = _client()

    proto.handle_rendezvous_message(
        HiveMessage(HiveMessageType.RENDEZVOUS, payload={"cmd": "collect"}),
        client)

    assert client.sent[0].payload["reason"] == "mailbox_error"


def test_the_mailbox_reply_reaches_the_client():
    proto = _protocol()
    proto.mailbox = _RecordingMailbox()
    client = _client()

    proto.handle_rendezvous_message(
        HiveMessage(HiveMessageType.RENDEZVOUS, payload={"cmd": "collect"}),
        client)

    assert client.sent[0].payload["status"] == "ok"


def test_handle_message_dispatches_rendezvous_to_the_handler():
    """The actual defect: RENDEZVOUS fell through to handle_unknown_message.

    This has to go through ``handle_message`` rather than calling the handler
    directly, or it passes with the dispatch branch deleted and proves nothing.
    """
    proto = _protocol()
    proto.mailbox = _RecordingMailbox()
    proto.handle_unknown_message = MagicMock()
    proto.update_last_seen = MagicMock()
    client = _client()

    proto.handle_message(
        HiveMessage(HiveMessageType.RENDEZVOUS, payload={"cmd": "collect"}),
        client)

    proto.handle_unknown_message.assert_not_called()
    assert proto.mailbox.calls, "RENDEZVOUS never reached the mailbox"
