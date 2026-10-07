"""服务层四态结论与规范摘要测试。"""

import unittest

from app.service import SPEC_NODE_LIMIT, verify_spec


def post(left, right, rules=None, **kw):
    payload = {"left": left, "right": right, "rules": rules or []}
    payload.update(kw)
    return verify_spec(payload)


class ServiceStatusTests(unittest.TestCase):
    def test_equivalent_commutative(self):
        out = post("f(a, b)", "f(b, a)", ["f(?x, ?y) = f(?y, ?x)"])
        self.assertEqual(out["status"], "equivalent")
        self.assertTrue(out["derivation"])
        self.assertEqual(out["summary"]["left"], "f(a, b)")
        self.assertEqual(out["summary"]["rule_count"], 1)

    def test_inequivalent_saturated_has_stable_summary_only(self):
        out = post("f(a, b)", "f(a, c)", ["f(?x, ?y) = f(?y, ?x)"])
        self.assertEqual(out["status"], "inequivalent")
        self.assertNotIn("derivation", out)  # 饱和非等价不带旧证据
        self.assertIn("fingerprint", out)
        self.assertGreaterEqual(len(out["classes"]), 2)
        again = post("f(a, b)", "f(a, c)", ["f(?x, ?y) = f(?y, ?x)"])
        self.assertEqual(again["fingerprint"], out["fingerprint"])

    def test_incomplete_resource_bound(self):
        out = post("a", "q", ["?x = f(?x)"],
                   node_limit=10, application_limit=1000)
        self.assertEqual(out["status"], "incomplete")
        self.assertIn("message", out)
        self.assertNotIn("classes", out)

    def test_invalid_syntax_clears_conclusion(self):
        out = post("f(a,", "f(b)", [])
        self.assertEqual(out["status"], "invalid")
        self.assertNotIn("derivation", out)
        self.assertNotIn("classes", out)
        self.assertTrue(out["errors"])

    def test_invalid_unbound_variable_in_query(self):
        out = post("f(?x, a)", "f(b, a)", [])
        self.assertEqual(out["status"], "invalid")
        self.assertTrue(
            any("未绑定变量" in e["message"] for e in out["errors"])
        )

    def test_invalid_rule_rhs_new_variable(self):
        out = post("f(a)", "f(b)", ["f(?x) = g(?x, ?y)"])
        self.assertEqual(out["status"], "invalid")
        self.assertTrue(any(e["scope"] == "rule" for e in out["errors"]))

    def test_invalid_too_many_rules(self):
        rules = ["a = b"] * 21
        out = post("a", "b", rules)
        self.assertEqual(out["status"], "invalid")

    def test_invalid_expression_over_node_limit(self):
        big = "a" + "(a" * (SPEC_NODE_LIMIT) + ")" * SPEC_NODE_LIMIT
        out = post(big, "a", [])
        self.assertEqual(out["status"], "invalid")

    def test_invalid_limit(self):
        out = post("a", "b", [], node_limit=0)
        self.assertEqual(out["status"], "invalid")

    def test_invalid_limit_non_numeric(self):
        out = post("a", "b", [], node_limit="abc")
        self.assertEqual(out["status"], "invalid")
        self.assertTrue(any(e["scope"] == "limits" for e in out["errors"]))

    def test_rules_newline_string(self):
        out = post("f(a,b)", "f(b,a)",
                   "f(?x, ?y) = f(?y, ?x)\n\n")
        self.assertEqual(out["status"], "equivalent")

    def test_summary_always_present(self):
        for payload in [
            {"left": "f(a,b)", "right": "f(b,a)", "rules": ["f(?x,?y)=f(?y,?x)"]},
            {"left": "f(a,b)", "right": "f(a,c)", "rules": []},
            {"left": "bad(", "right": "a", "rules": []},
        ]:
            out = verify_spec(payload)
            self.assertIn("summary", out)
            self.assertEqual(out["summary"]["spec_node_limit"], 80)


if __name__ == "__main__":
    unittest.main()
