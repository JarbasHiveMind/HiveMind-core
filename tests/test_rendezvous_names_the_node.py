"""A RENDEZVOUS answer says which node's mailbox produced it.

Mail is held by the node serving the request, and every node in a hive may
hold a mailbox. Two peers attached to different nodes each get a well-formed
answer — the collector gets `{"status": "ok", "messages": []}` — and neither
can tell it is reading a different dead drop from the one written to. The
exchange fails as silence, with no error anywhere to explain it.
"""
from unittest.mock import MagicMock

from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindClientConnection, HiveMindListenerProtocol


def _protocol(mailbox=None):
    protocol = HiveMindListenerProtocol(agent_protocol=MagicMock(), db=MagicMock())
    protocol.mailbox = mailbox
    return protocol


def _client(protocol, key="access-key"):
    sent = []
    client = HiveMindClientConnection(
        key=key, send_msg=MagicMock(), disconnect=MagicMock(),
        hm_protocol=protocol,
    )
    client.name = "sat"
    client.send = lambda msg, *a, **kw: sent.append(msg)
    return client, sent


def _request(cmd="collect"):
    return HiveMessage(HiveMessageType.RENDEZVOUS, {"cmd": cmd})


def test_an_answer_names_the_node_that_holds_the_mailbox():
    mailbox = MagicMock()
    mailbox.handle.return_value = HiveMessage(
        HiveMessageType.RENDEZVOUS, {"status": "ok", "messages": []})
    protocol = _protocol(mailbox)
    client, sent = _client(protocol)

    protocol.handle_rendezvous_message(_request(), client)

    assert sent
    assert sent[0].payload["mailbox_node"] == protocol._node_id


def test_two_nodes_are_distinguishable_by_their_answers():
    """The point of naming it: an empty collect from the wrong dead drop is
    indistinguishable from an empty collect from the right one."""
    answers = []
    for node_key in ("NODE-A", "NODE-B"):
        mailbox = MagicMock()
        mailbox.handle.return_value = HiveMessage(
            HiveMessageType.RENDEZVOUS, {"status": "ok", "messages": []})
        protocol = _protocol(mailbox)
        protocol.identity.public_key = node_key
        client, sent = _client(protocol)
        protocol.handle_rendezvous_message(_request(), client)
        answers.append(sent[0].payload["mailbox_node"])

    assert answers[0] != answers[1]


def test_the_result_of_the_command_is_untouched():
    """The control: naming the node must not disturb the answer itself."""
    mailbox = MagicMock()
    mailbox.handle.return_value = HiveMessage(
        HiveMessageType.RENDEZVOUS, {"status": "ok", "deposit_id": "abc-123"})
    protocol = _protocol(mailbox)
    client, sent = _client(protocol)

    protocol.handle_rendezvous_message(_request("deposit"), client)

    assert sent[0].payload["status"] == "ok"
    assert sent[0].payload["deposit_id"] == "abc-123"


def test_a_node_holding_no_mail_still_says_so():
    protocol = _protocol(mailbox=None)
    client, sent = _client(protocol)

    protocol.handle_rendezvous_message(_request(), client)

    assert sent[0].payload["reason"] == "not_a_rendezvous_node"


def test_the_answers_envelope_survives_naming():
    """A mailbox is documented as an optional third-party component. If it
    addresses its reply (metadata / target_site_id / target_pubkey), naming
    the node must not silently drop that envelope."""
    mailbox = MagicMock()
    mailbox.handle.return_value = HiveMessage(
        HiveMessageType.RENDEZVOUS, {"status": "ok", "messages": []},
        metadata={"trace": "t1"}, target_site_id="lab",
        target_pubkey="PEER-PUB")
    protocol = _protocol(mailbox)
    client, sent = _client(protocol)

    protocol.handle_rendezvous_message(_request(), client)

    reply = sent[0]
    assert reply.metadata == {"trace": "t1"}
    assert reply.target_site_id == "lab"
    assert reply.target_public_key == "PEER-PUB"
    # and the naming itself still happened
    assert reply.payload["mailbox_node"] == protocol._node_id


def test_a_node_with_no_mailbox_still_names_itself():
    """not_a_rendezvous_node lets a peer fail over; it must say which node
    just refused, same as any other RENDEZVOUS answer."""
    protocol = _protocol(mailbox=None)
    client, sent = _client(protocol)

    protocol.handle_rendezvous_message(_request(), client)

    assert sent[0].payload["mailbox_node"] == protocol._node_id


def test_an_unauthenticated_client_still_gets_a_named_refusal():
    protocol = _protocol(mailbox=MagicMock())
    client, sent = _client(protocol, key=None)

    protocol.handle_rendezvous_message(_request(), client)

    assert sent[0].payload["reason"] == "no_client_identity"
    assert sent[0].payload["mailbox_node"] == protocol._node_id


def test_a_node_with_no_identity_names_itself_none_not_missing():
    """A node whose identity has no public key yet (transitional: a separate
    PR guarantees every node has one) must not raise KeyError on the
    consumer side, and must not silently compare equal to another such
    node's answer as 'we met'."""
    mailbox = MagicMock()
    mailbox.handle.return_value = HiveMessage(
        HiveMessageType.RENDEZVOUS, {"status": "ok", "messages": []})
    protocol = _protocol(mailbox)
    protocol.identity.public_key = ""
    client, sent = _client(protocol)

    protocol.handle_rendezvous_message(_request(), client)

    assert "mailbox_node" in sent[0].payload
    assert sent[0].payload["mailbox_node"] is None
