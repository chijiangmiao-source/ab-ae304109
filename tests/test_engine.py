"""饱和重写引擎测试：交换律推导、同余闭包、饱和非等价、资源未完成。"""

import unittest

from app.engine import Engine
from app.parser import parse
from app.rules import parse_rule


def run_verify(left, right, rules, **kw):
    parsed = [parse_rule(i, r) for i, r in enumerate(rules)]
    engine = Engine(parsed, **kw)
    lid = engine._intern(parse(left), schedule=False)
    rid = engine._intern(parse(right), schedule=False)
    return engine.run(lid, rid)


COMMUTATIVE = ["f(?x, ?y) = f(?y, ?x)"]
GROUPLIKE = [
    "g(?x, ?y) = g(?y, ?x)",
    "g(?x, g(?y, ?z)) = g(g(?x, ?y), ?z)",
    "g(g(?x, ?y), ?z) = g(?x, g(?y, ?z))",
]


class EquivalenceTests(unittest.TestCase):
    def test_commutativity_direct(self):
        res = run_verify("f(a, b)", "f(b, a)", COMMUTATIVE)
        self.assertEqual(res.status, "equivalent")
        self.assertTrue(res.derivation)
        kinds = [s.kind for s in res.derivation]
        self.assertIn("rule", kinds)
        step = next(s for s in res.derivation if s.kind == "rule")
        self.assertEqual(step.before, "f(a, b)")
        self.assertEqual(step.after, "f(b, a)")
        self.assertEqual(step.detail["rule_text"], COMMUTATIVE[0])
        binds = {b["var"]: b["term"] for b in step.detail["bindings"]}
        self.assertEqual(binds, {"?x": "a", "?y": "b"})

    def test_commutativity_inside_context_needs_congruence(self):
        # h(f(a,b)) ~ h(f(b,a))：规则在子项上应用，外层靠同余
        res = run_verify("h(f(a, b))", "h(f(b, a))", COMMUTATIVE)
        self.assertEqual(res.status, "equivalent")
        self.assertIn("congruence", [s.kind for s in res.derivation])

    def test_group_rearrangement(self):
        res = run_verify("g(a, g(b, c))", "g(g(c, b), a)", GROUPLIKE)
        self.assertEqual(res.status, "equivalent")

    def test_constant_equation_with_congruence(self):
        res = run_verify("k(a, b)", "k(b, a)", ["a = b"])
        self.assertEqual(res.status, "equivalent")

    def test_rule_with_constants(self):
        res = run_verify("add(ZERO, a)", "a", ["add(ZERO, ?x) = ?x"])
        self.assertEqual(res.status, "equivalent")

    def test_reflexive(self):
        res = run_verify("f(a, b)", "f(a, b)", COMMUTATIVE)
        self.assertEqual(res.status, "equivalent")
        self.assertEqual(res.derivation, [])


class InequivalenceTests(unittest.TestCase):
    def test_no_rules_saturated(self):
        res = run_verify("f(a, b)", "f(a, c)", [])
        self.assertEqual(res.status, "inequivalent")
        # 森林含 f(a,b)、f(a,c)、a、b、c 五个哈希一致的项，各成单例类
        self.assertEqual(len(res.classes), 5)
        self.assertTrue(all(len(c.members) == 1 for c in res.classes))

    def test_saturated_different_classes(self):
        res = run_verify("h(a)", "h(c)", ["a = b"])
        self.assertEqual(res.status, "inequivalent")

    def test_stable_summary_fingerprint(self):
        r1 = run_verify("g(a, g(b, c))", "g(g(c, b), a)", GROUPLIKE)
        r2 = run_verify("g(a, g(b, c))", "g(g(c, b), a)", GROUPLIKE)
        self.assertEqual(r1.fingerprint, r2.fingerprint)
        # 摘要按确定顺序排列
        reps = [c.representative for c in r1.classes]
        self.assertEqual(reps, sorted(reps))

    def test_no_derivation_when_inequivalent(self):
        res = run_verify("f(a, b)", "f(a, c)", COMMUTATIVE)
        self.assertEqual(res.status, "inequivalent")
        self.assertFalse(hasattr(res, "derivation"))


class IncompleteTests(unittest.TestCase):
    def test_application_limit_zero(self):
        res = run_verify("a", "z", ["a = b"], application_limit=0)
        self.assertEqual(res.status, "incomplete")
        self.assertEqual(res.reason, "application_limit")

    def test_application_limit_mid_rewrite(self):
        # 交换律会在饱和前产生大量改写，极低上限必然未完成
        res = run_verify(
            "g(a, g(b, g(c, d)))", "g(d, g(c, g(b, a)))",
            GROUPLIKE, application_limit=3,
        )
        self.assertEqual(res.status, "incomplete")
        self.assertEqual(res.reason, "application_limit")

    def test_node_limit_with_expanding_rule(self):
        # ?x = f(?x) 反复外展，80 节点内无法穷尽
        res = run_verify("a", "q", ["?x = f(?x)"], node_limit=10,
                         application_limit=1000)
        self.assertEqual(res.status, "incomplete")
        self.assertEqual(res.reason, "node_limit")

    def test_incomplete_never_claims_equivalence(self):
        res = run_verify("a", "b", ["?x = f(?x)"], node_limit=6,
                         application_limit=1000)
        # 未饱和前即使产生合并也不允许给出等价/不等价判定
        self.assertEqual(res.status, "incomplete")
        self.assertGreater(res.node_limit, 0)


class DeterminismTests(unittest.TestCase):
    def test_repeated_runs_identical(self):
        results = []
        for _ in range(3):
            res = run_verify("g(a, g(b, c))", "g(g(c, b), a)", GROUPLIKE)
            results.append((res.status, res.fingerprint, res.applications, res.nodes))
        self.assertEqual(len(set(results)), 1)


if __name__ == "__main__":
    unittest.main()
