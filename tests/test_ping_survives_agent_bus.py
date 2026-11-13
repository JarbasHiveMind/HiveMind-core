"""Topology discovery must not depend on the agent backend.

A PING flood is how an operator asks which nodes are reachable. It is asked
precisely when something is wrong, and "the OVOS bus on that node is down" is
one of the things being diagnosed. Answering a flood needs nothing from the
agent bus: the reply is built from the node's own identity.

`hive.ping.received` is a telemetry emit on the way past, and the node already
treats agent-bus notifications that way everywhere else — `_emit_lifecycle`
logs and continues, because "the connection still has to be accepted, cleaned
up or rejected, and the peer has nothing to act on".
"""
from unittest.mock import MagicMock

from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindClientConnection, HiveMindListenerProtocol


def _protocol(bus_error=None):
    agent = MagicMock()
    if bus_error is not None:
        agent.bus.emit.side_effect = bus_error
    return HiveMindListenerProtocol(agent_protocol=agent, db=MagicMock())


def _client(protocol):
    sent = []
    client = HiveMindClientConnection(
        key="access-key", send_msg=MagicMock(), disconnect=MagicMock(),
        hm_protocol=protocol,
    )
    client.name = "sat"
    client.send = lambda *args, **kwargs: sent.append(args)
    # the answer fans out to connected peers, so the peer must be connected
    protocol.clients[client.peer] = client
    return client, sent


def _ping(flood_id="f1"):
    return HiveMessage(HiveMessageType.PING, {
        "flood_id": flood_id, "peer": "sat::1", "site_id": "lab",
        "timestamp": 1.0,
    })


def test_a_flood_is_answered_when_the_agent_bus_is_unreachable():
    protocol = _protocol(bus_error=ConnectionError("agent bus is down"))
    client, sent = _client(protocol)

    protocol.handle_ping_message(_ping(), client)

    assert sent, "an unreachable agent bus must not silence topology discovery"


def test_a_broken_agent_bus_does_not_raise_out_of_the_handler():
    """The handler runs on the connection's IO path; raising there takes the
    rest of the message's handling with it."""
    protocol = _protocol(bus_error=RuntimeError("bus exploded"))
    client, _ = _client(protocol)

    protocol.handle_ping_message(_ping(), client)  # must not raise


def test_the_flood_is_still_answered_when_the_bus_works():
    """The control: the telemetry emit is not what produces the answer."""
    protocol = _protocol()
    client, sent = _client(protocol)

    protocol.handle_ping_message(_ping(), client)

    assert sent


def test_the_observation_is_still_published_when_the_bus_works():
    protocol = _protocol()
    client, _ = _client(protocol)

    protocol.handle_ping_message(_ping(), client)

    emitted = [c.args[0].msg_type for c in protocol.agent_protocol.bus.emit.call_args_list]
    assert "hive.ping.received" in emitted
