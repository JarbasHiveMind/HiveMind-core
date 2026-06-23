"""Regression tests for issue #117 — unencrypted INTERCOM inner BUS dropped.

``handle_intercom_message`` only deserialized the inner payload in the
``"ciphertext"`` branch and then dispatched on the OUTER message's
``msg_type`` (always ``INTERCOM``), which matches no branch — so an
unencrypted intercom carrying an inner BUS (or PROPAGATE/BROADCAST/...)
was silently dropped. The inner HiveMessage must be deserialized and
dispatched on its own (inner) type in both the encrypted and unencrypted
cases.
"""
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from hivemind_bus_client.message import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindListenerProtocol


def _make_protocol():
    proto = object.__new__(HiveMindListenerProtocol)
    proto.identity = MagicMock(public_key="OUR_PUBKEY")
    proto.handle_bus_message = MagicMock()
    proto.handle_propagate_message = MagicMock()
    proto.handle_broadcast_message = MagicMock()
    proto.handle_escalate_message = MagicMock()
    proto.handle_binary_message = MagicMock()
    proto.handle_client_shared_bus = MagicMock()
    return proto


def _unencrypted_intercom(inner, target_pubkey=None):
    return HiveMessage(
        HiveMessageType.INTERCOM,
        payload=inner,
        target_pubkey=target_pubkey,
    )


def test_unencrypted_inner_bus_is_delivered():
    proto = _make_protocol()
    client = MagicMock()
    inner = HiveMessage(HiveMessageType.BUS,
                        payload=Message("speak", {"utterance": "hi"}))

    handled = proto.handle_intercom_message(_unencrypted_intercom(inner), client)

    assert handled is True
    proto.handle_bus_message.assert_called_once()
    dispatched = proto.handle_bus_message.call_args.args[0]
    assert dispatched.msg_type == HiveMessageType.BUS
    assert dispatched.payload.msg_type == "speak"


def test_unencrypted_inner_propagate_is_delivered():
    proto = _make_protocol()
    client = MagicMock()
    bus = HiveMessage(HiveMessageType.BUS, payload=Message("speak", {}))
    inner = HiveMessage(HiveMessageType.PROPAGATE, payload=bus)

    handled = proto.handle_intercom_message(_unencrypted_intercom(inner), client)

    assert handled is True
    proto.handle_propagate_message.assert_called_once()
    proto.handle_bus_message.assert_not_called()


def test_intercom_for_other_pubkey_is_ignored():
    proto = _make_protocol()
    client = MagicMock()
    inner = HiveMessage(HiveMessageType.BUS, payload=Message("speak", {}))

    handled = proto.handle_intercom_message(
        _unencrypted_intercom(inner, target_pubkey="SOMEONE_ELSE"), client)

    assert handled is False
    proto.handle_bus_message.assert_not_called()
