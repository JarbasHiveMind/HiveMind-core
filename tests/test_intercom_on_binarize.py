"""INTERCOM framing on a binarize connection (HIVEMIND-WIRE-1 §4.3).

WIRE-1 §4.2 assigns a 5-bit message-type code to twelve types. INTERCOM has
none, so §4.3 requires it to travel as a text frame even when the connection
negotiated binary framing, and requires a receiver to accept both forms on the
same connection.

The client side has always honoured this (``hivemind_bus_client.client`` gates
on ``BINARY_ENCODABLE_TYPES``). The server did not: it binarized whatever it
sent as soon as ``binarize`` was set, and ``get_bitstring`` raises for a type
with no code, so a server could not send an INTERCOM at all to a binarize
client. These tests pin the server side of §4.3.
"""

import unittest
from unittest.mock import MagicMock

from ovos_bus_client.message import Message

from hivemind_bus_client import HiveMessage, HiveMessageType
from hivemind_core.protocol import HiveMindClientConnection


def _binarize_client(**kwargs):
    client = HiveMindClientConnection(
        key="test-key",
        send_msg=MagicMock(),
        disconnect=MagicMock(),
        handshake=MagicMock(),
        **kwargs,
    )
    client.name = "test-client"
    client.binarize = True
    return client


def _intercom():
    return HiveMessage(HiveMessageType.INTERCOM,
                       payload={"ciphertext": "deadbeef",
                                "target_public_key": "peer-pubkey"})


class TestIntercomTextOnBinarizeConnection(unittest.TestCase):
    """WIRE-1 §4.3: a codeless type stays text on a binary-framing link."""

    def test_intercom_is_sent_as_text_when_binarize_negotiated(self):
        client = _binarize_client()
        client.send(_intercom())
        payload, is_bin = client.send_msg.call_args[0]
        assert is_bin is False
        assert HiveMessage.deserialize(payload).msg_type == HiveMessageType.INTERCOM

    def test_intercom_is_sent_as_text_on_a_noise_binarize_connection(self):
        client = _binarize_client()
        client.noise_transport = MagicMock()
        client.noise_transport.send_message.side_effect = (
            lambda payload, raw_send: raw_send(b"noise-frame"))
        client.send(_intercom())
        framed = client.noise_transport.send_message.call_args[0][0]
        assert HiveMessage.deserialize(framed).msg_type == HiveMessageType.INTERCOM

    def test_a_coded_type_still_binarizes_on_the_same_connection(self):
        # both forms coexist on one connection: BUS has a code, INTERCOM has not
        client = _binarize_client()
        client.noise_transport = MagicMock()
        client.noise_transport.send_message.side_effect = (
            lambda payload, raw_send: raw_send(b"noise-frame"))
        client.send(HiveMessage(HiveMessageType.BUS,
                                payload=Message("speak", {"utterance": "hi"})))
        # a coded type on a binarize connection is framed as binary bytes
        framed = client.noise_transport.send_message.call_args[0][0]
        assert isinstance(framed, bytes)
        _, is_bin = client.send_msg.call_args[0]
        assert is_bin is True
