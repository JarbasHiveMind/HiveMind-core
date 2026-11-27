"""Core-side proof that the protocol call sites drive multi-frame Noise.

``HiveMindClientConnection.send`` must hand an oversize v3 payload to
``NoiseTransport.send_message`` (which chunks it), and ``decode`` must return
``None`` for an in-progress chunk and the full HiveMessage only on the LAST
chunk. This exercises the two protocol.py call sites edited for #45.
"""
import unittest
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_bus_client.noise import (
    CHUNK_SIZE,
    NOISE_PATTERN_XX,
    NOISE_SUITE_CHACHA,
    NoiseTransport,
    build_prologue,
    noise_protocol_name,
    start_noise_handshake,
)
from hivemind_core.protocol import (HiveMindClientConnection,
                                    HiveMindListenerProtocol)


def _pair():
    prologue = build_prologue(
        {"node_id": "server"}, {"max_protocol_version": 3},
        noise_protocol_name(NOISE_PATTERN_XX, NOISE_SUITE_CHACHA))
    common = dict(pattern=NOISE_PATTERN_XX, suite=NOISE_SUITE_CHACHA,
                  node_id="server")
    a = start_noise_handshake(initiator=True, password="s3cr3t",
                              prologue=prologue, **common)
    b = start_noise_handshake(initiator=False, password="s3cr3t",
                              prologue=prologue, **common)
    b.read_message(a.write_message(b"hi"))
    a.read_message(b.write_message(b"ho"))
    b.read_message(a.write_message(b""))
    return NoiseTransport(a), NoiseTransport(b)


def _make_protocol():
    agent = MagicMock()
    agent.bus = MagicMock()
    db = MagicMock()
    return HiveMindListenerProtocol(agent_protocol=agent, db=db)


def _make_client(protocol, transport):
    client = HiveMindClientConnection(
        key="test-key", send_msg=MagicMock(), disconnect=MagicMock(),
        hm_protocol=protocol)
    client.name = "test-client"
    client.noise_transport = transport
    return client


class TestCoreSendChunks(unittest.TestCase):
    def test_send_large_bus_message_is_chunked_and_reassembles(self):
        ta, tb = _pair()
        proto = _make_protocol()
        sender = _make_client(proto, ta)
        receiver = _make_client(proto, tb)

        big = "x" * (CHUNK_SIZE * 2)  # ~130KB payload, well over one frame
        msg = HiveMessage(HiveMessageType.BUS,
                          payload=Message("recognizer_loop:b64_transcribe",
                                          {"audio": big}))
        # avoid the binary path so the large JSON body drives text chunking
        sender.binarize = False
        sender.send(msg)

        frames = [c.args[0] for c in sender.send_msg.call_args_list]
        self.assertGreater(len(frames), 1, "large message was not chunked")

        decoded = [receiver.decode(f) for f in frames]
        # every frame but the last reassembles to None
        self.assertTrue(all(d is None for d in decoded[:-1]))
        result = decoded[-1]
        self.assertIsNotNone(result)
        self.assertEqual(result.msg_type, HiveMessageType.BUS)
        self.assertEqual(result.payload.data["audio"], big)

    def test_send_small_message_is_single_frame(self):
        ta, tb = _pair()
        proto = _make_protocol()
        sender = _make_client(proto, ta)
        receiver = _make_client(proto, tb)

        msg = HiveMessage(HiveMessageType.BUS,
                          payload=Message("speak", {"utterance": "hi"}))
        sender.binarize = False
        sender.send(msg)
        frames = [c.args[0] for c in sender.send_msg.call_args_list]
        self.assertEqual(len(frames), 1)
        result = receiver.decode(frames[0])
        self.assertIsNotNone(result)
        self.assertEqual(result.payload.data["utterance"], "hi")


if __name__ == "__main__":
    unittest.main()
