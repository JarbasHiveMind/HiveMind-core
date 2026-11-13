"""Guard: every coded close goes through ``close_connection``.

``close_connection`` adapts a close to the signature of the transport's own
``disconnect``. A coded ``<client>.disconnect(code, reason)`` call anywhere
else in ``hivemind_core.protocol`` bypasses that adaptation, so the module is
parsed and every such call outside the helper is reported.
"""
import ast
import unittest


class TestNoCodedCloseBypassesTheHelper(unittest.TestCase):
    """A coded ``disconnect`` call in the module is the defect, so read it."""

    @staticmethod
    def _coded_closes_outside_the_helper(source):
        """Every ``<x>.disconnect(<args>)`` call outside ``close_connection``.

        Parsed, not matched line by line, so a call written across several
        lines, or one whose text equals a line inside the helper, is still
        found.

        Only the module-level helper is excluded. A method or a nested
        function of the same name is a different function, and its body is
        read like any other.
        """
        tree = ast.parse(source)
        helper_ranges = [
            (node.lineno, node.end_lineno)
            for node in tree.body
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

        # the plain case
        self.assertEqual(
            len(self._coded_closes_outside_the_helper(
                helper + "def kick(c):\n    c.disconnect(1008, 'x')\n")),
            1)
        # written across several lines
        self.assertEqual(
            len(self._coded_closes_outside_the_helper(
                helper + "def kick(c):\n    c.disconnect(\n        1008,\n"
                         "        'x')\n")),
            1)
        # text identical to a line inside the helper
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

    def test_only_the_module_level_helper_is_excluded(self):
        """A function of that name in another scope is not the helper.

        The exclusion window belongs to the module-level
        ``close_connection``. A method or a nested function carrying the
        same name would otherwise hide every coded close in its body, which
        is the one thing this guard exists to report.
        """
        helper = ("def close_connection(client, code, reason):\n"
                  "    client.disconnect(code, reason)\n\n")

        method = (helper + "class Session:\n"
                           "    def close_connection(self):\n"
                           "        self.client.disconnect(1008, 'hidden')\n")
        self.assertEqual(
            len(self._coded_closes_outside_the_helper(method)), 1,
            "a method of that name must not open an exclusion window")

        nested = (helper + "def unrelated(victim):\n"
                           "    def close_connection():\n"
                           "        victim.disconnect(1008, 'hidden')\n")
        self.assertEqual(
            len(self._coded_closes_outside_the_helper(nested)), 1,
            "a nested function of that name must not open one either")
