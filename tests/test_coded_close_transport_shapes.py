"""Every coded close goes through ``close_connection``, on any shape.

``close_connection`` reads the transport's own ``disconnect`` signature, so a
transport that cannot take a close code is closed without one instead of
raising ``TypeError`` out of the handler. Three coded closes did not use it,
and it did not cover every shape.

THE THREE SITES. ``HiveMindClientConnection._reject`` called
``self.disconnect(code, reason)``, which serves the three 1008 crypto
rejections. ``handle_hello_message`` called
``client.disconnect(1008, ...)`` for the protocol-v3 requirement, and the
Noise-handshake failure called ``client.disconnect(1008, close_reason)``.
Each carried the same exposure the helper exists to remove.

TWO SHAPES THE HELPER GOT WRONG. It read one binding, ``(code, reason)``
positionally, and fell to an uncoded ``disconnect()`` when that failed:

* A keyword-only ``disconnect(*, code=1000, reason="")`` does not bind two
  positional arguments, so the kick fell through to the uncoded call and the
  transport sent its own default 1000. The close code was lost with no sign
  of it, which is worse than raising.
* A ``disconnect(code)`` with one required positional argument binds neither
  two arguments nor zero, so the uncoded fallback raised ``TypeError`` for
  the argument it still needed. The fallback was itself unsafe.

The shapes are now tried best first, so a transport receives as much of the
close as its signature accepts and never less.
"""
import ast
import unittest

from hivemind_core.protocol import close_connection


class _Recorder:
    """A stand-in connection whose ``disconnect`` records how it was called."""

    def __init__(self, disconnect):
        self.disconnect = disconnect


def _zero_arg(seen):
    def disconnect():
        seen.append({})
    return disconnect


def _defaults(seen):
    def disconnect(code=1000, reason=""):
        seen.append({"code": code, "reason": reason})
    return disconnect


def _one_required_positional(seen):
    def disconnect(code):
        seen.append({"code": code})
    return disconnect


def _keyword_only(seen):
    def disconnect(*, code=1000, reason=""):
        seen.append({"code": code, "reason": reason})
    return disconnect


def _reason_only_keyword(seen):
    def disconnect(code, *, reason=""):
        seen.append({"code": code, "reason": reason})
    return disconnect


def _positional_only_code_keyword_only_reason(seen):
    """CodeRabbit's shape: no single-kind call binds this at all.

    The code cannot be passed by keyword and the reason cannot be passed
    positionally, so before the mixed shape existed the whole table missed
    and the fallback raised ``TypeError`` with the client still connected.
    """
    def disconnect(code, /, *, reason):
        seen.append({"code": code, "reason": reason})
    return disconnect


def _crossed_names(seen):
    """A transport that takes the reason FIRST.

    It accepts two positional arguments, so arity alone binds it and hands it
    the integer code as its reason and the text reason as its code. Nothing
    raises. It declares both names, so the keyword shape serves it.
    """
    def disconnect(reason, code=1000):
        seen.append({"reason": reason, "code": code})
    return disconnect


def _reason_only(seen):
    """A transport that names a reason and no code at all."""
    def disconnect(reason=""):
        seen.append({"reason": reason})
    return disconnect


class TestCloseConnectionCarriesTheCodeItCan(unittest.TestCase):

    def _close(self, shape):
        seen = []
        client = _Recorder(shape(seen))
        close_connection(client, 1008, "policy kick")
        return seen

    def test_a_transport_with_defaults_gets_both(self):
        """The control: the shape every transport in this repository uses."""
        self.assertEqual(self._close(_defaults),
                         [{"code": 1008, "reason": "policy kick"}])

    def test_a_keyword_only_transport_gets_the_code(self):
        """It used to receive the transport default 1000 and no reason."""
        self.assertEqual(self._close(_keyword_only),
                         [{"code": 1008, "reason": "policy kick"}])

    def test_a_one_argument_transport_gets_the_code(self):
        """It used to raise TypeError from the uncoded fallback."""
        self.assertEqual(self._close(_one_required_positional),
                         [{"code": 1008}])

    def test_a_mixed_positional_and_keyword_transport_gets_both(self):
        self.assertEqual(self._close(_reason_only_keyword),
                         [{"code": 1008, "reason": "policy kick"}])

    def test_a_positional_only_code_with_a_keyword_only_reason_gets_both(self):
        """The shape no entry in the old table could bind.

        It did not merely lose the reason: nothing bound, the fallback made
        the coded call, that raised ``TypeError`` out of the handler, and the
        client this helper exists to drop stayed connected.
        """
        seen = []
        close_connection(_Recorder(_positional_only_code_keyword_only_reason(seen)),
                         1008, "noise handshake failed")
        self.assertEqual(seen, [{"code": 1008,
                                 "reason": "noise handshake failed"}])

    def test_a_transport_that_takes_the_reason_first_is_not_crossed(self):
        """Arity is not enough: it binds, and it binds them the wrong way."""
        seen = []
        close_connection(_Recorder(_crossed_names(seen)), 4003, "policy kick")
        self.assertEqual(seen, [{"reason": "policy kick", "code": 4003}],
                         "the transport must not be handed the code as its "
                         "reason")

    def test_a_transport_with_a_reason_and_no_code_gets_the_reason(self):
        """It carries what it can, rather than the code crossed into it."""
        seen = []
        close_connection(_Recorder(_reason_only(seen)), 1008, "kicked")
        self.assertEqual(seen, [{"reason": "kicked"}])

    def test_a_zero_argument_transport_is_still_closed(self):
        """hivemind-email's shape. It cannot carry a code, so it carries none.

        The point is that the client IS disconnected. Raising here is the
        defect the helper exists to prevent: the kick would stop kicking.
        """
        self.assertEqual(self._close(_zero_arg), [{}])

    def test_no_shape_raises(self):
        """None of the five shapes may raise out of close_connection."""
        for shape in (_zero_arg, _defaults, _one_required_positional,
                      _keyword_only, _reason_only_keyword):
            with self.subTest(shape=shape.__name__):
                try:
                    self._close(shape)
                except TypeError as exc:
                    self.fail(f"{shape.__name__} raised TypeError: {exc}")

    def test_a_transport_error_still_propagates(self):
        """A TypeError raised INSIDE disconnect is not read as a bad shape.

        This is why the signature is read instead of the call being wrapped
        in ``except TypeError``. A transport whose own code is broken must
        still say so.
        """
        def disconnect(code=1000, reason=""):
            raise TypeError("the transport itself is broken")

        with self.assertRaises(TypeError) as caught:
            close_connection(_Recorder(disconnect), 1008, "policy kick")
        self.assertIn("the transport itself is broken", str(caught.exception))


class TestNoCodedCloseBypassesTheHelper(unittest.TestCase):
    """A coded ``disconnect`` call in the module is the defect, so read it.

    A reviewer cannot tell from behaviour alone that a new coded close was
    added straight onto the transport, and the next one will be written by
    somebody who has not read this file.
    """

    @staticmethod
    def _coded_closes_outside_the_helper(source):
        """Every ``<x>.disconnect(<args>)`` call outside ``close_connection``.

        Parsed, not matched line by line. A line filter missed the exact call
        this test exists to catch as soon as it was written across two lines,
        and it also excluded an outside call whose text happened to equal a
        line inside the helper. Neither needs unusual code: the first is what
        line-length pressure produces, the second is the identical call.
        """
        tree = ast.parse(source)
        helper_ranges = [
            (node.lineno, node.end_lineno)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "close_connection"
        ]

        def inside_the_helper(lineno):
            return any(start <= lineno <= end for start, end in helper_ranges)

        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "disconnect":
                continue
            if not (node.args or node.keywords):
                continue          # the uncoded close is allowed anywhere
            if inside_the_helper(node.lineno):
                continue
            found.append(f"line {node.lineno}: {ast.unparse(node)}")
        return found

    def test_the_module_makes_no_coded_disconnect_call_outside_the_helper(self):
        import inspect

        from hivemind_core import protocol

        outside = self._coded_closes_outside_the_helper(
            inspect.getsource(protocol))
        self.assertEqual(outside, [],
                         "a coded close must go through close_connection")

    def test_the_guard_catches_what_the_line_filter_let_through(self):
        """The guard is measured on source of this test's own making.

        Without this, a guard that reports nothing is indistinguishable from
        a guard that cannot see anything.
        """
        helper = ("def close_connection(client, code, reason):\n"
                  "    client.disconnect(code, reason)\n")

        # the plain case the old line filter did catch
        self.assertEqual(
            len(self._coded_closes_outside_the_helper(
                helper + "def kick(c):\n    c.disconnect(1008, 'x')\n")),
            1)
        # written across two lines: the old filter MISSED this
        self.assertEqual(
            len(self._coded_closes_outside_the_helper(
                helper + "def kick(c):\n    c.disconnect(\n        1008,\n"
                         "        'x')\n")),
            1)
        # text identical to a line inside the helper: the old filter MISSED it
        self.assertEqual(
            len(self._coded_closes_outside_the_helper(
                helper + "def kick(client, code, reason):\n"
                         "    client.disconnect(code, reason)\n")),
            1)
        # an UNCODED close outside the helper stays allowed
        self.assertEqual(
            self._coded_closes_outside_the_helper(
                helper + "def bye(c):\n    c.disconnect()\n"),
            [])
        # and the helper's own coded call is not reported
        self.assertEqual(self._coded_closes_outside_the_helper(helper), [])

    def test_the_line_filter_this_replaces_missed_both_cases(self):
        """The control for the guard itself.

        A stricter guard that catches nothing new is not stricter. This runs
        the filter this test used to use over the same two sources and
        records that it reported them clean.
        """
        import re

        old = re.compile(r"\.disconnect\(\s*[^)\s]")
        helper_line = "    client.disconnect(code, reason)"

        def old_guard(source):
            return [line.strip() for line in source.splitlines()
                    if old.search(line) and line != helper_line]

        across_two_lines = ("def kick(c):\n"
                            "    c.disconnect(\n"
                            "        1008,\n"
                            "        'x')\n")
        text_of_a_helper_line = ("def kick(client, code, reason):\n"
                                 + helper_line + "\n")

        self.assertEqual(old_guard(across_two_lines), [],
                         "the old filter is expected to miss this")
        self.assertEqual(old_guard(text_of_a_helper_line), [],
                         "the old filter is expected to miss this")
