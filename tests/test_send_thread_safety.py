"""Concurrent ``HiveMindClientConnection.send`` must not reorder v3 frames.

A protocol v3 (Noise) session assigns a strictly sequential nonce per
outgoing frame, so the order in which frames reach the socket must match the
order in which they were encrypted. Three distinct threads send on the same
connection (the IOLoop thread, the ovos messagebus thread and the upstream
slave thread); if any of them is preempted between encrypting and enqueueing,
the peer's ``decrypt_frame`` fails the AEAD check and drops the session.
"""

import threading
import time
import unittest
from unittest.mock import MagicMock

from hivemind_bus_client import HiveMessage, HiveMessageType

from hivemind_core.protocol import HiveMindClientConnection


class FakeNoiseTransport:
    """Mimics NoiseTransport's locking: the nonce is assigned under a lock
    which is released before the frame is handed back to the caller."""

    def __init__(self, yield_after_encrypt=True):
        self._send_lock = threading.Lock()
        self._nonce = 0
        self._yield_after_encrypt = yield_after_encrypt

    def encrypt_frame(self, payload):
        with self._send_lock:
            nonce = self._nonce
            self._nonce += 1
        if self._yield_after_encrypt:
            time.sleep(0)
        return nonce


class TestConcurrentSendOrdering(unittest.TestCase):
    def test_v3_frames_reach_the_socket_in_nonce_order(self):
        sent = []
        sent_lock = threading.Lock()

        def send_msg(payload, is_bin):
            with sent_lock:
                sent.append(payload)

        client = HiveMindClientConnection(
            key="test-key",
            send_msg=send_msg,
            disconnect=MagicMock(),
            hm_protocol=MagicMock(),
        )
        client.noise_transport = FakeNoiseTransport()

        message = HiveMessage(HiveMessageType.BUS, payload={"type": "speak"})
        frames_per_thread = 200
        start = threading.Barrier(3)

        def sender():
            start.wait()
            for _ in range(frames_per_thread):
                client.send(message)

        threads = [threading.Thread(target=sender) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(sent), 3 * frames_per_thread)
        inversions = [(a, b) for a, b in zip(sent, sent[1:]) if b != a + 1]
        self.assertEqual(inversions, [],
                         f"frames left send() out of nonce order: {inversions[:5]}")


if __name__ == "__main__":
    unittest.main()
