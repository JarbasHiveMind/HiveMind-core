"""A satellite can not address another satellite's connection, end to end.

Two real satellites connect to one master, announcing the same name and
declaring the same session id, so their peer ids differ only by the suffix the
master appends on a collision. The agent is hivescope's TestAgentProtocol,
whose reverse routing is a port of the OVOS agent's: any agent-bus message
whose ``destination`` names a connected peer is delivered to that peer.

One satellite then writes the other's peer id into ``destination``. The
built-in ``PeerDestinationPolicy`` denies it before the agent bus sees it, so
the other satellite receives nothing. Replies the agent addresses to a
satellite, and a satellite addressing a service or itself, still flow.
"""
import time

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivescope.topology import TopologyBuilder
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

NAME = "KitchenSatellite"
SESSION = "s-1"
TYPES = ["recognizer_loop:utterance", "ovos.utterance.speak",
         "mycroft.volume.get.response"]
INJECTED = "the front door is unlocked"


def _wait_for(condition, timeout: float = 2.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


def _twins():
    b = TopologyBuilder()
    m = b.add_master("M0")
    for name in ("A", "B"):
        b.add_satellite(name, upstream=m, allowed_types=TYPES)
        sat = b.get_satellite(name)
        sat.identity.name = NAME
        sat.shim._session_id = SESSION
    b.start_all()
    a, s = b.get_satellite("A"), b.get_satellite("B")
    assert a.peer.startswith(f"{NAME}::{SESSION}")
    assert s.peer.startswith(f"{NAME}::{SESSION}")
    assert a.peer != s.peer
    return b, m, a, s


def _send(satellite, msg_type, data, destination):
    context = {"session": Session(session_id=SESSION, site_id="site").serialize(),
               "destination": destination}
    satellite.send(HiveMessage(HiveMessageType.BUS,
                               payload=Message(msg_type, data, context)))


def _collect(satellite, msg_type):
    got = []
    satellite.internal_bus.on(msg_type, got.append)
    return got


def test_a_satellite_can_not_make_another_one_speak():
    b, m, a, s = _twins()
    try:
        for sender, victim in ((s, a), (a, s)):
            heard = _collect(victim, "ovos.utterance.speak")
            denied = _collect(sender, "hive.policy.denied")

            _send(sender, "ovos.utterance.speak", {"utterance": INJECTED}, victim.peer)

            assert _wait_for(lambda: denied), "the sender was not told it was denied"
            assert denied[0].data["code"] == "peer_destination_forbidden"
            assert denied[0].data["data"] == {"destination": [victim.peer]}
            assert heard == []
        assert m.agent_protocol.last_injected("ovos.utterance.speak") is None
    finally:
        b.stop_all()


def test_a_list_destination_can_not_hide_another_satellite():
    b, m, a, s = _twins()
    try:
        heard = _collect(a, "mycroft.volume.get.response")
        denied = _collect(s, "hive.policy.denied")

        _send(s, "mycroft.volume.get.response", {"percent": 1.0}, ["skills", s.peer, a.peer])

        assert _wait_for(lambda: denied)
        assert denied[0].data["data"] == {"destination": [a.peer]}
        assert heard == []
    finally:
        b.stop_all()


def test_legitimate_routing_still_flows():
    b, m, a, s = _twins()
    try:
        agent = m.agent_protocol
        denied = _collect(a, "hive.policy.denied")

        # a satellite addressing a service: admitted, stamped with its peer
        _send(a, "recognizer_loop:utterance", {"utterances": ["what time is it"]}, "skills")
        assert _wait_for(lambda: agent.last_injected("recognizer_loop:utterance") is not None)
        assert agent.last_injected("recognizer_loop:utterance").context["peer"] == a.peer

        # the agent answering that satellite: delivered to it alone
        heard_a = _collect(a, "ovos.utterance.speak")
        heard_s = _collect(s, "ovos.utterance.speak")
        m.emit_on_bus(Message("ovos.utterance.speak", {"utterance": "it is noon"},
                              {"destination": a.peer, "source": "skills"}))
        assert _wait_for(lambda: heard_a)
        assert heard_s == []

        # a mid-turn reply addressed back to the agent, and one a satellite
        # addresses to its own connection
        _send(a, "mycroft.volume.get.response", {"percent": 0.4}, "hive")
        own = _collect(a, "mycroft.volume.get.response")
        _send(a, "mycroft.volume.get.response", {"percent": 0.4}, a.peer)
        assert _wait_for(lambda: own)
        replies = [x for x in agent.injected if x.msg_type == "mycroft.volume.get.response"]
        assert len(replies) == 2
        assert denied == []
    finally:
        b.stop_all()
