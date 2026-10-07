"""解析器与规则校验测试。"""

import unittest

from app.parser import (
    ParseError,
    has_variables,
    iter_vars,
    node_count,
    parse,
)
from app.rules import MAX_RULES, RuleError, parse_rule


class ParserTests(unittest.TestCase):
    def test_constant_and_calls(self):
        self.assertEqual(str(parse("ALT_LIMIT")), "ALT_LIMIT")
        self.assertEqual(str(parse("f(a)")), "f(a)")
        self.assertEqual(str(parse("g(f(a), b)")), "g(f(a), b)")

    def test_variables_marked(self):
        t = parse("f(?x, g(?y, a))")
        self.assertEqual(iter_vars(t), {"x", "y"})
        self.assertTrue(has_variables(t))
        self.assertFalse(has_variables(parse("f(a, b)")))
        self.assertEqual(str(t), "f(?x, g(?y, a))")

    def test_node_count(self):
        self.assertEqual(node_count(parse("a")), 1)
        self.assertEqual(node_count(parse("f(a,b)")), 3)
        self.assertEqual(node_count(parse("f(g(a),b)")), 4)

    def test_syntax_errors(self):
        for bad in ["", "   ", "f(a", "f(a,)", "f(a,b,c)", "123", "a + b",
                    "f(?)", "?(x)", "f(a b)", "f()"]:
            with self.subTest(bad=bad):
                with self.assertRaises(ParseError):
                    parse(bad)

    def test_no_tail_junk(self):
        with self.assertRaises(ParseError):
            parse("f(a) x")


class RuleTests(unittest.TestCase):
    def test_ok(self):
        r = parse_rule(0, "f(?x, ?y) = f(?y, ?x)")
        self.assertEqual(str(r.lhs), "f(?x, ?y)")
        self.assertEqual(str(r.rhs), "f(?y, ?x)")

    def test_constant_equation(self):
        r = parse_rule(1, "a = b")
        self.assertFalse(iter_vars(r.lhs))

    def test_rhs_new_var_rejected(self):
        with self.assertRaises(RuleError):
            parse_rule(0, "f(?x) = g(?x, ?y)")

    def test_missing_equal(self):
        with self.assertRaises(RuleError):
            parse_rule(0, "f(?x) -> g(?x)")

    def test_overlong_rule_rejected(self):
        big = "a" + "(a" * 80 + ")" * 80
        self.assertGreater(node_count(parse(big)), 80)
        with self.assertRaises(RuleError):
            parse_rule(0, f"{big} = a")

    def test_max_rules_constant(self):
        self.assertEqual(MAX_RULES, 20)


if __name__ == "__main__":
    unittest.main()
