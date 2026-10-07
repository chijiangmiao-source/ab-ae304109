"""解析器测试（标准库 unittest）。"""

import unittest

from app.engine.parser import (
    ParseError,
    canonical,
    node_count,
    parse,
    parse_rule,
    substitute,
    variables,
)


class ParserTests(unittest.TestCase):
    def test_parse_named_constant(self):
        t = parse("alpha")
        self.assertEqual(t.symbol, "alpha")
        self.assertEqual(t.args, ())
        self.assertEqual(canonical(t), "alpha")

    def test_parse_unary_and_binary(self):
        t = parse("f(g(a), h(b))")
        self.assertEqual(t.symbol, "f")
        self.assertEqual(len(t.args), 2)
        self.assertEqual(canonical(t), "f(g(a),h(b))")

    def test_parse_rejects_bad_syntax(self):
        bad = [
            "",
            "   ",
            "f(a,,b)",
            "f(a,b",
            "f(a,b,c)",
            "f(1)",
            "f(a) + g(b)",
            "(a)",
            "f()",
        ]
        for text in bad:
            with self.subTest(text=text):
                with self.assertRaises(ParseError):
                    parse(text)

    def test_parse_rule_and_variables(self):
        lhs, rhs = parse_rule("add(x, y) = add(y, x)")
        self.assertEqual(variables(lhs), frozenset({"x", "y"}))
        self.assertEqual(canonical(lhs), "add(x,y)")
        self.assertEqual(canonical(rhs), "add(y,x)")

    def test_parse_rule_missing_equals(self):
        with self.assertRaises(ParseError):
            parse_rule("f(x) g(x)")

    def test_node_count(self):
        self.assertEqual(node_count(parse("a")), 1)
        self.assertEqual(node_count(parse("f(a,b)")), 3)
        self.assertEqual(node_count(parse("f(g(a),b)")), 4)

    def test_substitute(self):
        t = parse("add(x, y)")
        out = substitute(t, {"x": parse("a"), "y": parse("g(b)")})
        self.assertEqual(canonical(out), "add(a,g(b))")


if __name__ == "__main__":
    unittest.main()
