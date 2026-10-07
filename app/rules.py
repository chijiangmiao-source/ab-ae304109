"""等式规则：解析与变量约束校验。

规则形如 ``lhs = rhs``，两侧均为受限表达式。以 ? 开头的标识符是
（元）变量，其余是具名常量；右侧不得引入左侧未出现的变量。
"""

from __future__ import annotations

from dataclasses import dataclass

from .parser import ParseError, Term, iter_vars, node_count, parse

__all__ = ["Rule", "RuleError", "MAX_NODES", "MAX_RULES"]

MAX_NODES = 80
MAX_RULES = 20


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    index: int
    raw: str
    lhs: Term
    rhs: Term

    def __str__(self) -> str:
        return self.raw


def parse_rule(index: int, raw: str, max_nodes: int = MAX_NODES) -> Rule:
    text = raw.strip() if isinstance(raw, str) else ""
    if not text:
        raise RuleError(f"第 {index + 1} 条规则为空")
    if "=" not in text:
        raise RuleError(f"第 {index + 1} 条规则缺少 '='：{raw!r}")
    left, _, right = text.partition("=")
    if "=" in right:
        raise RuleError(f"第 {index + 1} 条规则含有多个 '='：{raw!r}")
    try:
        lhs = parse(left)
        rhs = parse(right)
    except ParseError as exc:
        raise RuleError(f"第 {index + 1} 条规则{exc}") from exc

    lhs_vars = iter_vars(lhs)
    rhs_vars = iter_vars(rhs)
    extra = sorted(v for v in rhs_vars if v not in lhs_vars)
    if extra:
        raise RuleError(
            f"第 {index + 1} 条规则右侧引入了左侧未出现的变量："
            f"{', '.join(extra)}"
        )
    if node_count(lhs) > max_nodes or node_count(rhs) > max_nodes:
        raise RuleError(
            f"第 {index + 1} 条规则超过 {max_nodes} 个节点的声明上限"
        )
    return Rule(index=index, raw=text, lhs=lhs, rhs=rhs)
