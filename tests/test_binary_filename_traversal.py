"""Regression tests for issue #119 — BINARY(FILE) path traversal.

``handle_binary_message`` must not pass a client-supplied ``file_name``
verbatim to ``handle_receive_file``: a malicious peer could send
``../../etc/passwd`` and escape the intended download directory. The
protocol layer must ``os.path.basename`` the name (and reject empty / "."
/ ".." results) before handing it to the binary backend.
"""
from unittest.mock import MagicMock

from hivemind_bus_client.message import (
    HiveMessage,
    HiveMessageType,
    HiveMindBinaryPayloadType,
)

from hivemind_core.policy import PolicyChain
from hivemind_core.protocol import HiveMindListenerProtocol


class _RecordingBinaryProtocol:
    """Captures the file_name handed to handle_receive_file."""

    def __init__(self):
        self.received = []

    def handle_receive_file(self, bin_data, file_name, client):
        self.received.append(file_name)


def _make_protocol():
    proto = object.__new__(HiveMindListenerProtocol)
    proto.binary_data_protocol = _RecordingBinaryProtocol()
    # empty chain allows everything
    proto.policy_chain = PolicyChain()
    return proto


def _file_message(file_name):
    return HiveMessage(
        HiveMessageType.BINARY,
        payload=b"malicious-bytes",
        bin_type=HiveMindBinaryPayloadType.FILE,
        metadata={"file_name": file_name},
    )


def test_traversal_filename_is_basenamed():
    proto = _make_protocol()
    client = MagicMock()
    proto.handle_binary_message(_file_message("../../etc/passwd"), client)
    assert proto.binary_data_protocol.received == ["passwd"]


def test_absolute_path_is_basenamed():
    proto = _make_protocol()
    client = MagicMock()
    proto.handle_binary_message(_file_message("/etc/shadow"), client)
    assert proto.binary_data_protocol.received == ["shadow"]


def test_plain_filename_passes_through():
    proto = _make_protocol()
    client = MagicMock()
    proto.handle_binary_message(_file_message("notes.txt"), client)
    assert proto.binary_data_protocol.received == ["notes.txt"]


def test_dotdot_only_is_rejected():
    proto = _make_protocol()
    client = MagicMock()
    proto.handle_binary_message(_file_message("../.."), client)
    # basename("../..") == ".." -> rejected, nothing handed to backend
    assert proto.binary_data_protocol.received == []


def test_empty_filename_is_rejected():
    proto = _make_protocol()
    client = MagicMock()
    proto.handle_binary_message(_file_message(""), client)
    assert proto.binary_data_protocol.received == []
