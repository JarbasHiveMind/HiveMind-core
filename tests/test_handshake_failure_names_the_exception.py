"""A Noise handshake abort must name the exception that caused it.

The two abort sites in ``handle_noise_handshake_message`` built their reason
with ``f"handshake failure: {e}"``. An exception constructed with no
arguments renders as the empty string, so both the node log line and the
client's close reason read

    handshake failure:

and name nothing. The client then raises

    ConnectionRefusedError: HiveMind refused this identity: handshake failure:

which is what the nightly burst in hivemind-test-harness produced. The run
log could not say which failure it was, so the cause could not be read back
from it.

This is a diagnostic fix. It does not change which handshakes succeed.
"""
import unittest

from hivemind_core.protocol import _handshake_failure_text


class _Bare(Exception):
    """An exception whose str() is empty, like the one the burst produced."""


class TestTheFailureTextNamesSomething(unittest.TestCase):

    def test_an_exception_with_no_message_still_names_its_type(self):
        """The defect: this used to render as the empty string."""
        self.assertEqual(_handshake_failure_text(_Bare()), "_Bare")
        self.assertNotEqual(str(_Bare()), "_Bare",
                            "the bare f-string would have produced this")

    def test_an_exception_with_a_message_keeps_both(self):
        self.assertEqual(_handshake_failure_text(ValueError("boom")),
                         "ValueError: boom")

    def test_whitespace_only_counts_as_no_message(self):
        self.assertEqual(_handshake_failure_text(_Bare("   ")), "_Bare")

    def test_the_result_is_never_empty(self):
        """Whatever the exception, the operator gets a name."""
        for exc in (_Bare(), ValueError(""), ValueError("  "), KeyError(),
                    RuntimeError("real"), OSError(), _Bare(None)):
            with self.subTest(exc=repr(exc)):
                self.assertTrue(_handshake_failure_text(exc).strip(),
                                "an abort reason must name something")

    def test_the_reason_reaches_the_close_frame(self):
        """The whole point: the client's close reason carries the name.

        A fix that only changed the log line would leave the client raising
        ``ConnectionRefusedError: ... handshake failure:`` with nothing in it.
        """
        reason = f"handshake failure: {_handshake_failure_text(_Bare())}"
        self.assertIn("_Bare", reason)
        self.assertNotEqual(reason.rstrip(), "handshake failure:")


class TestBothAbortSitesUseIt(unittest.TestCase):
    """Neither site may keep the bare interpolation.

    Only one of the two was reached by the burst; a fix to one alone leaves
    the other silent in exactly the same way.
    """

    def test_no_abort_site_interpolates_the_exception_bare(self):
        import inspect
        import re

        from hivemind_core import protocol

        source = inspect.getsource(protocol)
        # only a real call site, not the helper docstring that quotes the
        # old form
        bare = re.findall(
            r'_abort_noise_handshake\(\s*client,\s*f"handshake failure: \{e\}"',
            source)
        self.assertEqual(bare, [],
                         "an abort site still renders the exception bare, so "
                         "an argument-less exception names nothing")

    def test_both_sites_route_through_the_helper(self):
        import inspect

        from hivemind_core import protocol

        source = inspect.getsource(protocol)
        self.assertEqual(
            source.count("_handshake_failure_text(e)"), 2,
            "both Noise handshake abort sites must name the exception")
