"""A duplicate HANDSHAKE frame drops the frame, not the session.

``handle_noise_handshake_message`` guarded two states against a
client-controlled duplicate or replayed HANDSHAKE frame, and both guards
aborted the handshake:

* the Noise session is already established (``noise_transport`` is set)
* the pre-shared key is still being derived (``noise_psk_pending``)

Aborting closes the connection with 1008 and records
``noise_handshake_failed``. The client reads that as a refused identity,
latches it and stops reconnecting, so a correctly registered satellite left
the mesh until it was restarted.

THIS IS THE MEASURED CAUSE OF THE NIGHTLY RED in hivemind-test-harness,
``test_listener_releases_every_client_after_a_burst``. In a reproduced
failure the satellite was registered and then removed, and its client held

    _auth_rejected = 'unexpected HANDSHAKE frame after the Noise session
                      was established'

with the registry one entry short for the rest of the run.

It is also a denial of service. One injected or replayed HANDSHAKE frame on
an established connection ended that connection, and the client's latch made
the loss permanent.

The early return is what protects the handshake state; the abort added
nothing to that and cost the session. The client already treats the mirror
case this way: ``hivemind_bus_client`` ignores a HANDSHAKE frame once its
own Noise session is established, calling it "a stray retry/offer from the
peer, not a new negotiation".
"""
import unittest
from unittest.mock import MagicMock, patch

from hivemind_core.protocol import HiveMindListenerProtocol


def _client(established=False, psk_pending=False):
    client = MagicMock()
    client.peer = "sat-1::sess::test"
    client.noise_transport = MagicMock() if established else None
    client.noise_psk_pending = psk_pending
    client.noise_handshake = None
    client.disconnected = False
    return client


def _protocol():
    protocol = HiveMindListenerProtocol.__new__(HiveMindListenerProtocol)
    return protocol


class TestAnEstablishedSessionSurvivesADuplicate(unittest.TestCase):

    def _deliver(self, client):
        """Feed one HANDSHAKE frame carrying a Noise message."""
        protocol = _protocol()
        message = MagicMock()
        message.payload = {"noise": {"msg": "00" * 8}}
        with patch.object(HiveMindListenerProtocol, "_abort_noise_handshake") as abort:
            protocol.handle_noise_handshake_message(message, client)
        return abort

    def test_the_session_is_not_aborted(self):
        """The defect: this used to close the connection with 1008."""
        client = _client(established=True)
        abort = self._deliver(client)
        abort.assert_not_called()

    def test_the_transport_is_left_alone(self):
        """Dropping the frame must not touch the live session either.

        An abort cleared noise_transport and set disconnected; a test that
        only checked for the absence of a close would pass even if the
        session had been torn down by hand.
        """
        client = _client(established=True)
        transport = client.noise_transport
        self._deliver(client)
        self.assertIs(client.noise_transport, transport)
        self.assertFalse(client.disconnected)

    def test_a_malformed_envelope_does_not_end_an_established_session(self):
        """The guard must sit ABOVE the envelope parse.

        The parse aborts on bad hex, and that is right DURING a handshake.
        On an established session there is no handshake state for it to
        protect, so aborting there only ended a healthy session: one byte of
        bad hex cleared the transport, recorded 1008 noise_handshake_failed
        and disconnected, which is the same latch the guard exists to stop.
        The first version of this fix left that path open.
        """
        for label, payload in (("bad hex", {"noise": {"msg": "zz"}}),
                               ("no msg key", {"noise": {}}),
                               ("no noise key", {})):
            with self.subTest(payload=label):
                client = _client(established=True)
                transport = client.noise_transport
                protocol = _protocol()
                message = MagicMock()
                message.payload = payload
                with patch.object(HiveMindListenerProtocol,
                                  "_abort_noise_handshake") as abort:
                    protocol.handle_noise_handshake_message(message, client)
                abort.assert_not_called()
                self.assertIs(client.noise_transport, transport)
                self.assertFalse(client.disconnected)

    def test_a_malformed_envelope_still_aborts_during_a_handshake(self):
        """The control, and it must not move with the thing it controls.

        Moving the guard above the parse must not stop a mid-handshake
        malformed envelope from aborting. If this passed too, the change
        would have disabled the parse check rather than reordered it.
        """
        for label, payload in (("bad hex", {"noise": {"msg": "zz"}}),
                               ("no msg key", {"noise": {}})):
            with self.subTest(payload=label):
                client = _client()          # no established transport
                protocol = _protocol()
                message = MagicMock()
                message.payload = payload
                with patch.object(HiveMindListenerProtocol,
                                  "_abort_noise_handshake") as abort:
                    protocol.handle_noise_handshake_message(message, client)
                abort.assert_called_once()
                self.assertIn("malformed Noise envelope",
                              abort.call_args[0][1])

    def test_the_duplicate_reaches_no_handshake_state(self):
        """The original guard's actual purpose still holds.

        ``noise_handshake`` is None on an established session, and the frame
        must not be fed to it.
        """
        client = _client(established=True)
        self._deliver(client)
        self.assertIsNone(client.noise_handshake)


class TestAPendingDerivationSurvivesADuplicate(unittest.TestCase):

    def test_a_duplicate_during_psk_derivation_is_not_aborted(self):
        """The same class, and the one a burst makes likely.

        argon2id derivation is slow on purpose, so a second frame arriving
        while it runs is the expected shape under load, not an attack.
        """
        client = _client(psk_pending=True)
        client.pswd_handshake = MagicMock(password="pw")
        # the pattern and suite must be ones the server offered, or the
        # negotiation check above the guard refuses first and this asserts
        # nothing
        client._handshake_payload = {
            "noise": {"patterns": ["XXpsk2"],
                      "suites": ["25519_ChaChaPoly_BLAKE2s"]}}
        client._hello_payload = {}
        protocol = _protocol()
        protocol._get_pinned_client_noise_key = MagicMock(return_value=None)
        protocol._cached_noise_psk = MagicMock(return_value=None)
        protocol._noise_psk_key = MagicMock(return_value="k")
        protocol._derive_noise_psk_async = MagicMock()
        message = MagicMock()
        message.payload = {"noise": {"msg": "00" * 8, "pattern": "XXpsk2",
                                     "suite": "25519_ChaChaPoly_BLAKE2s"}}
        with patch.object(HiveMindListenerProtocol,
                          "_abort_noise_handshake") as abort:
            # No try/except. The call must RETURN, not raise: an earlier
            # version swallowed everything here, so an exception raised before
            # the abort satisfied the assertion below just as a clean drop
            # did, and the test could not tell them apart.
            protocol.handle_noise_handshake_message(message, client)

        abort.assert_not_called()
        # and the drop really happened: the guard returns above the derivation
        # work, so neither of these runs for a dropped frame. Without them a
        # frame that fell through and merely failed to abort would pass.
        protocol._cached_noise_psk.assert_not_called()
        protocol._derive_noise_psk_async.assert_not_called()


class TestNeitherGuardAborts(unittest.TestCase):
    """Both sites, because fixing one leaves the other killing sessions."""

    def test_no_duplicate_frame_guard_calls_abort(self):
        import inspect
        import re

        from hivemind_core import protocol

        source = inspect.getsource(protocol.HiveMindListenerProtocol
                                   .handle_noise_handshake_message)
        for phrase in ("after the Noise session was established",
                       "pre-shared key is being derived"):
            with self.subTest(guard=phrase):
                self.assertNotIn(
                    phrase, source,
                    "a duplicate-frame guard still aborts the handshake, so "
                    "a replayed frame still ends a healthy session")
        # and the drops are there instead
        self.assertEqual(
            len(re.findall(r"ignoring a HANDSHAKE frame", source)), 2,
            "both duplicate-frame guards must drop the frame and log it")
