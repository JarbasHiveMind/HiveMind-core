"""ACL enforcement: blacklisted OVOS message types are dropped before delivery."""

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from ovos_bus_client.message import Message

from hivescope.scenarios import single_satellite


def test_blacklisted_type_not_delivered_to_satellite():
    b = single_satellite()
    b.start_all()
    try:
        m0 = b.get_master("M0")
        s0 = b.get_satellite("S0")

        # Blacklist "speak" on the live connection.
        conn = m0.hm_protocol.clients[s0.peer]
        conn.msg_blacklist = ["speak"]

        seen = []
        s0.shim.emitter.on(
            HiveMessageType.BUS,
            lambda msg: seen.append(msg)
            if isinstance(msg.payload, Message) and msg.payload.msg_type == "speak"
            else None,
        )

        m0.send_to_satellite(
            s0.peer,
            HiveMessage(
                HiveMessageType.BUS,
                payload=Message("speak", {"utterance": "should not arrive"}),
            ),
        )

        assert seen == [], f"Blacklisted 'speak' was delivered: {seen}"
    finally:
        b.stop_all()


def test_non_blacklisted_type_still_delivered():
    b = single_satellite()
    b.start_all()
    try:
        m0 = b.get_master("M0")
        s0 = b.get_satellite("S0")

        conn = m0.hm_protocol.clients[s0.peer]
        conn.msg_blacklist = ["speak"]

        seen = []
        s0.shim.emitter.on(HiveMessageType.BUS, seen.append)

        m0.send_to_satellite(
            s0.peer,
            HiveMessage(
                HiveMessageType.BUS,
                payload=Message("recognizer_loop:utterance", {"utterances": ["hi"]}),
            ),
        )

        assert len(seen) == 1, f"Non-blacklisted message was dropped: {seen}"
    finally:
        b.stop_all()
