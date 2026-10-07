"""引擎判定测试：覆盖四类结论、同余、证据与确定性（unittest）。"""

import unittest

from app.engine.api import (
    EQUIVALENT,
    INVALID,
    NOT_EQUIVALENT,
    UNKNOWN,
    analyze,
)
from app.engine.matching import RuleError, make_rule
from app.engine.parser import parse_rule


def run(left, right, rules, **kw):
    return analyze({"left": left, "right": right, "rules": rules, **kw})


def _all_steps(proof):
    """展平包含同余前提子证据的全部步骤。"""
    out = []
    for step in proof:
        out.append(step)
        for child in step.get("premise_proofs", []) or []:
            out.extend(_all_steps(child.get("steps", [])))
    return out


class EquivalenceTests(unittest.TestCase):
    def test_commutativity_equivalent_with_congruence(self):
        r = run("f(add(a,b))", "f(add(b,a))", ["add(x,y) = add(y,x)"])
        self.assertEqual(r["status"], EQUIVALENT)
        self.assertTrue(r["proof"])
        kinds = [s["by"]["kind"] for s in r["proof"]]
        self.assertIn("congruence", kinds)
        self.assertEqual(r["proof"][0]["from"], "f(add(a,b))")
        self.assertEqual(r["proof"][-1]["to"], "f(add(b,a))")

    def test_rule_instance_records_substitution(self):
        r = run("f(add(a,b))", "f(add(b,a))", ["add(x,y) = add(y,x)"])
        flat = _all_steps(r["proof"])
        rule_steps = [s for s in flat if s["by"]["kind"] == "rule"]
        self.assertTrue(rule_steps, "规则实例必须出现在证据或同余前提中")
        for step in rule_steps:
            self.assertEqual(
                step["by"]["rule_text"], "add(x,y) = add(y,x)"
            )
            self.assertEqual(set(step["by"]["substitution"]), {"x", "y"})

    def test_congruence_carries_premises(self):
        r = run("f(add(a,b))", "f(add(b,a))", ["add(x,y) = add(y,x)"])
        top = r["proof"]
        cong = [s for s in top if s["by"]["kind"] == "congruence"]
        self.assertTrue(cong and cong[0].get("premise_proofs"))
        premise = cong[0]["premise_proofs"][0]
        self.assertEqual(premise["from"], "add(a,b)")
        self.assertEqual(premise["to"], "add(b,a)")
        self.assertTrue(
            any(s["by"]["kind"] == "rule" for s in premise["steps"])
        )

    def test_assoc_and_comm_chain(self):
        r = run(
            "add(add(a,b),c)",
            "add(a,add(c,b))",
            ["add(x,y) = add(y,x)", "add(add(x,y),z) = add(x,add(y,z))"],
        )
        self.assertEqual(r["status"], EQUIVALENT)
        self.assertEqual(r["proof"][0]["from"], "add(add(a,b),c)")
        self.assertEqual(r["proof"][-1]["to"], "add(a,add(c,b))")

    def test_unary_rule_congruence(self):
        r = run("g(f(a))", "g(g(a))", ["f(x) = g(x)"])
        self.assertEqual(r["status"], EQUIVALENT)
        self.assertTrue(
            any(s["by"]["kind"] == "congruence" for s in r["proof"])
        )

    def test_identical_expressions_empty_proof(self):
        r = run("f(g(a))", "f(g(a))", [])
        self.assertEqual(r["status"], EQUIVALENT)
        self.assertEqual(r["proof"], [])

    def test_rule_direction_can_apply_reverse(self):
        r = run("f(a)", "g(a)", ["g(x) = f(x)"])
        self.assertEqual(r["status"], EQUIVALENT)

    def test_nested_rewrite_deep(self):
        # 深层嵌套中交换律仍能逐层同余传播。
        rules = ["add(x,y) = add(y,x)"]
        r = run(
            "g(h(add(a,add(b,c))))",
            "g(h(add(add(c,b),a)))",
            rules,
        )
        self.assertEqual(r["status"], EQUIVALENT)


class VariableConventionTests(unittest.TestCase):
    """单小写字母为变量，其余叶子为必须字面匹配的具名常量。"""

    def test_identity_rule_with_named_constant(self):
        r = run("add(a,zero)", "a", ["add(x,zero) = x"])
        self.assertEqual(r["status"], EQUIVALENT)

    def test_named_constant_must_match_literally(self):
        # 第二参数是 b 而不是具名常量 zero，规则不应触发。
        r = run("add(a,b)", "a", ["add(x,zero) = x"])
        self.assertEqual(r["status"], NOT_EQUIVALENT)

    def test_collapsing_rule_forward_only_guarded(self):
        # g(x)=zero：正向 g(a)≈zero；反向不得凭空把无关叶子 a 并入。
        self.assertEqual(
            run("g(a)", "zero", ["g(x) = zero"])["status"], EQUIVALENT
        )
        self.assertEqual(
            run("zero", "a", ["g(x) = zero"])["status"], NOT_EQUIVALENT
        )

    def test_rhs_may_introduce_named_constant_but_not_variable(self):
        self.assertEqual(
            run("a", "a", ["f(x) = g(x,zero)"])["status"], EQUIVALENT
        )
        self.assertEqual(
            run("a", "a", ["f(x) = g(x,y)"])["status"], INVALID
        )

    def test_long_identifiers_are_constants_not_variables(self):
        # nil 是具名常量，规则只能字面重写 nil，不匹配任意项。
        r = run("nil", "cons(a,nil)", ["nil = empty"])
        # nil≈empty，但 cons(a,nil) 不等于 nil。
        self.assertEqual(r["status"], NOT_EQUIVALENT)
        self.assertEqual(
            run("nil", "empty", ["nil = empty"])["status"], EQUIVALENT
        )


class NotEquivalentTests(unittest.TestCase):
    def test_saturated_distinct_classes(self):
        r = run("a", "b", [])
        self.assertEqual(r["status"], NOT_EQUIVALENT)
        self.assertIsNone(r["proof"])
        self.assertNotEqual(r["left_class"], r["right_class"])
        self.assertEqual(len(r["classes"]), 2)
        for c in r["classes"]:
            self.assertEqual(len(c["digest"]), 16)

    def test_no_spurious_merges(self):
        r = run("f(a)", "g(a)", [])
        self.assertEqual(r["status"], NOT_EQUIVALENT)

    def test_summary_is_stable(self):
        r1 = run("a", "b", [])
        r2 = run("a", "b", [])
        self.assertEqual(
            [c["digest"] for c in r1["classes"]],
            [c["digest"] for c in r2["classes"]],
        )
        r3 = run("b", "a", [])
        self.assertEqual(
            sorted(c["digest"] for c in r1["classes"]),
            sorted(c["digest"] for c in r3["classes"]),
        )

    def test_members_sorted_and_deterministic(self):
        r = run("z", "a", [])
        for c in r["classes"]:
            self.assertEqual(c["members"], sorted(c["members"]))


class UnknownTests(unittest.TestCase):
    def test_node_limit_blocks_saturation(self):
        r = run("a", "g(b)", ["x = d(f(x))"], max_nodes=80)
        self.assertEqual(r["status"], UNKNOWN)
        self.assertIsNone(r["proof"])
        self.assertIsNone(r["classes"])
        self.assertIn("80", r["limit_reason"])

    def test_application_limit_blocks_saturation(self):
        r = run(
            "a",
            "g(b)",
            ["x = d(f(x))"],
            max_nodes=80,
            max_applications=20,
        )
        self.assertEqual(r["status"], UNKNOWN)
        self.assertGreaterEqual(r["stats"]["rule_applications"], 20)
        self.assertIn("上限", r["limit_reason"])

    def test_collapsing_rules_saturate(self):
        r = run("f(a)", "a", ["x = f(x)"])
        self.assertEqual(r["status"], EQUIVALENT)


class InvalidTests(unittest.TestCase):
    def test_syntax_error(self):
        r = run("f(a,b", "a", [])
        self.assertEqual(r["status"], INVALID)
        self.assertIsNone(r["proof"])
        self.assertIsNone(r["classes"])
        self.assertTrue(
            any(i["code"] == "parse_error" for i in r["issues"])
        )

    def test_unbound_variable(self):
        r = run("a", "b", ["f(x) = g(y)"])
        self.assertEqual(r["status"], INVALID)
        self.assertTrue(
            any(i["code"] == "unbound_variable" for i in r["issues"])
        )

    def test_too_many_rules(self):
        rules = [f"f(x{i}) = x{i}" for i in range(21)]
        r = run("a", "b", rules)
        self.assertEqual(r["status"], INVALID)
        self.assertTrue(
            any(i["code"] == "too_many_rules" for i in r["issues"])
        )

    def test_seed_over_node_limit(self):
        big = "f(" * 80 + "a" + ")" * 80
        r = run(big, "a", [])
        self.assertEqual(r["status"], INVALID)
        self.assertTrue(
            any(i["code"] == "node_limit" for i in r["issues"])
        )

    def test_rule_side_over_limit(self):
        huge = "f(" * 80 + "x" + ")" * 80
        r = run("a", "b", [f"x = {huge}"])
        self.assertEqual(r["status"], INVALID)
        self.assertTrue(
            any(i["code"] == "node_limit" for i in r["issues"])
        )

    def test_boundary_80_nodes_allowed(self):
        ok = "f(" * 79 + "a" + ")" * 79
        r = run(ok, ok, [])
        self.assertEqual(r["status"], EQUIVALENT)

    def test_make_rule_rejects_extra_rhs_variables(self):
        lhs, rhs = parse_rule("h(x) = k(x,y)")
        with self.assertRaises(RuleError):
            make_rule(1, lhs, rhs, "h(x) = k(x,y)")

    def test_empty_expressions_invalid(self):
        r = run("", "b", [])
        self.assertEqual(r["status"], INVALID)


class StatelessnessTests(unittest.TestCase):
    def test_invalid_after_equivalent_has_no_stale_evidence(self):
        good = run("f(add(a,b))", "f(add(b,a))", ["add(x,y) = add(y,x)"])
        self.assertEqual(good["status"], EQUIVALENT)
        self.assertTrue(good["proof"])
        bad = run("f(add(a,b))", "f(add(b,a)", ["add(x,y) = add(y,x)"])
        self.assertEqual(bad["status"], INVALID)
        self.assertIsNone(bad["proof"])
        self.assertIsNone(bad["classes"])

    def test_not_equivalent_after_equivalent_has_no_stale_proof(self):
        run("f(add(a,b))", "f(add(b,a))", ["add(x,y) = add(y,x)"])
        r = run("a", "b", [])
        self.assertEqual(r["status"], NOT_EQUIVALENT)
        self.assertIsNone(r["proof"])
        # 饱和摘要仍然可用。
        self.assertIsNotNone(r["classes"])


if __name__ == "__main__":
    unittest.main()
