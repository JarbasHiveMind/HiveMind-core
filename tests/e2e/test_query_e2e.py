"""QUERY e2e: a satellite issues a QUERY; the master's local agent answers
synchronously through the policy admission chain; the response is routed back
to the originating satellite.
"""
import time

import pytest

pytest.importorskip("hivescope")

import inspect  # noqa: E402


def _bus_client_has_query_companion() -> bool:
    """The QUERY round-trip needs the bus-client companion fix: handle_query
    must unwrap to ``handle_bus(message.payload)``, not pass the QUERY wrapper."""
    try:
        from hivemind_bus_client.protocol import HiveMindSlaveProtocol
        return "message.payload" in inspect.getsource(HiveMindSlaveProtocol.handle_query)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _bus_client_has_query_companion(),
    reason="needs hivemind-bus-client QUERY companion (handle_query -> handle_bus(message.payload))",
)

from hivemind_bus_client.message import HiveMessage, HiveMessageType  # noqa: E402
from ovos_bus_client.message import Message  # noqa: E402
from hivescope.topology import TopologyBuilder  # noqa: E402


def test_query_local_agent_round_trip():
    b = TopologyBuilder()
    m = b.add_master("M0")
    m.register_satellite("sat-key", password="sat-pw",
                         allowed_types=["recognizer_loop:utterance"])
    s = b.add_satellite("S0", upstream=m,
                        allowed_types=["recognizer_loop:utterance"])
    b.start_all()
    try:
        master = b.get_master("M0")
        sat = b.get_satellite("S0")

        # local agent answers any utterance
        def _responder(msg):
            master.agent_protocol.bus.emit(
                msg.response(data={"answer": "the weather is sunny"}))
        master.agent_protocol.bus.on("recognizer_loop:utterance", _responder)

        inner = HiveMessage(HiveMessageType.BUS,
                            payload=Message("recognizer_loop:utterance",
                                            {"utterances": ["weather"]}))
        sat.send(HiveMessage(HiveMessageType.QUERY, payload=inner,
                             metadata={"query_id": "q1", "originator_peer": sat.peer}))

        # the satellite receives an inbound QUERY — the agent's response routed
        # back to the originator (wait_for already filters direction="in" + QUERY)
        recv = sat.recorder.wait_for(HiveMessageType.QUERY.value,
                                     direction="in", timeout=2.0)
        assert recv is not None, "satellite never received a QUERY response"
    finally:
        b.stop_all()
