"""Provenance fields must carry this node's real identity, not a constant.

``HiveMindListenerProtocol.peer`` is the class default ``"master:0.0.0.0"``
and ``service.py`` never overrides it, so every node in every deployment
announced the same string. Loop detection was already moved to
``self._node_id`` (the node public key) for exactly that reason; the other
provenance and addressing uses were left behind:

* ``_unpack_message`` -> ``update_source_peer``
* the responsive PING payload ``peer``
* ``responder_peer`` on QUERY/CASCADE responses

These tests build nodes the way production does — shared default ``peer``,
distinct public keys — and pin every one of those fields to the public key.
"""
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from hivemind_bus_client.hive_map import FloodIdCache
from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivemind_bus_client.hive_map import FloodIdCache

from hivemind_core.protocol import HiveMindListenerProtocol

DEFAULT_PEER = "master:0.0.0.0"
NODE_KEY = "pubkey-of-this-node"


def _make_node() -> HiveMindListenerProtocol:
    node = object.__new__(HiveMindListenerProtocol)
    node.peer = DEFAULT_PEER
    node.identity = MagicMock(public_key=NODE_KEY, site_id="site-a")
    node.clients = {}
    node.hive_mapper = MagicMock()
    node.agent_protocol = MagicMock()
    node._seen_flood_ids = FloodIdCache()
    node._answered_floods = FloodIdCache()
    # _answer_query_locally runs the utterance/dialog pipelines. __post_init__
    # builds them for a real node; a bypass-built one has the None default, so
    # give it empty (no-op) services rather than letting the query path raise.
    from ovos_plugin_manager.transformer_services import (
        DialogTransformersService, MetadataTransformersService,
        UtteranceTransformersService)
    node.utterance_transformers = UtteranceTransformersService(config={})
    node.metadata_transformers = MetadataTransformersService(config={})
    node.dialog_transformers = DialogTransformersService(config={})
    node._last_ping_flood = 0.0
    node.ping_flood_interval = 0.0
    node._upstream_hm = None
    return node


def _client() -> MagicMock:
    client = MagicMock()
    client.peer = "satellite::1"
    return client


def test_unpacked_message_source_peer_is_the_node_key():
    node = _make_node()
    inner = HiveMessage(HiveMessageType.BUS,
                        payload=Message("speak", {"utterance": "hi"}))
    outer = HiveMessage(HiveMessageType.PROPAGATE, payload=inner)

    payload = node._unpack_message(outer, _client())

    assert payload.source_peer == NODE_KEY, (
        "a relayed payload must name this node by its public key, not the "
        f"shared default {DEFAULT_PEER!r}")


def test_responsive_ping_announces_the_node_key():
    node = _make_node()
    sent = []
    conn = _client()
    conn.send = lambda m, *a: sent.append(m)
    node.clients = {conn.peer: conn}
    node.propagate_to_master = lambda msg: None

    ping = HiveMessage(HiveMessageType.PING, payload={
        "flood_id": "flood-1", "peer": "somewhere-else",
        "site_id": "site-b", "timestamp": 0})
    node.handle_ping_message(ping, _client())

    assert sent, "an unseen flood must be re-flooded to peers"
    payload = sent[0].payload.payload
    assert payload["peer"] == NODE_KEY, (
        "the responsive PING must announce this node's public key, not the "
        f"shared default {DEFAULT_PEER!r}")


def test_query_response_responder_peer_is_the_node_key():
    node = _make_node()
    node.default_lang = "en-US"
    node.agent_protocol.answer_query.return_value = iter(["hello there"])
    node._admit_for_query = lambda message, client: message

    inner = HiveMessage(HiveMessageType.BUS,
                        payload=Message("recognizer_loop:utterance",
                                        {"utterances": ["hi"]}))
    query = HiveMessage(HiveMessageType.QUERY, payload=inner,
                        metadata={"query_id": "q1"})
    sent = []
    answered = node._answer_query_locally(
        query, _client(), "q1", "satellite::1",
        HiveMessageType.QUERY, query.route, sent.append)

    assert answered and sent
    for response in sent:
        assert response.metadata["responder_peer"] == NODE_KEY, (
            "a query response must identify the answering node by public "
            f"key, not the shared default {DEFAULT_PEER!r}")
