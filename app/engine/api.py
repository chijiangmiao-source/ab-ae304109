"""复核 API：校验输入、驱动饱和引擎、产出规范摘要与结论。

结论状态
--------

* ``equivalent``    —— 闭包饱和后两式处于同一等价类；
* ``not_equivalent``—— 闭包饱和后两式分属不同等价类（附稳定摘要）；
* ``unknown``       —— 达到节点/应用次数上限前未能饱和（未完成）；
* ``invalid``       —— 语法错误、未绑定变量或超限规则（不携带旧结论）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .matching import (
    DEFAULT_MAX_APPLICATIONS,
    DEFAULT_MAX_NODES,
    Engine,
    RuleError,
    make_rule,
)
from .parser import (
    ParseError,
    Term,
    canonical,
    node_count,
    parse,
    parse_rule,
)

MAX_RULES = 20

EQUIVALENT = "equivalent"
NOT_EQUIVALENT = "not_equivalent"
UNKNOWN = "unknown"
INVALID = "invalid"

STATUS_LABELS = {
    EQUIVALENT: "等价",
    NOT_EQUIVALENT: "不等价",
    UNKNOWN: "未完成",
    INVALID: "无效",
}


@dataclass
class ValidationIssue:
    code: str
    message: str
    field: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out = {"code": self.code, "message": self.message}
        if self.field is not None:
            out["field"] = self.field
        return out


@dataclass
class AnalysisRequest:
    left_text: str
    right_text: str
    rule_texts: Sequence[str] = field(default_factory=list)
    max_nodes: int = DEFAULT_MAX_NODES
    max_applications: int = DEFAULT_MAX_APPLICATIONS


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def analyze(payload: Dict[str, Any]) -> Dict[str, Any]:
    """执行一次完整复核；返回可直接 JSON 序列化的结论。

    该函数无状态：每次调用都从空闭包开始，因此无效输入天然不会
    残留任何旧结论或旧证据。
    """

    issues: List[ValidationIssue] = []

    max_nodes = _coerce_limit(
        payload.get("max_nodes", DEFAULT_MAX_NODES),
        DEFAULT_MAX_NODES,
        "max_nodes",
        issues,
    )
    max_applications = _coerce_limit(
        payload.get("max_applications", DEFAULT_MAX_APPLICATIONS),
        DEFAULT_MAX_APPLICATIONS,
        "max_applications",
        issues,
    )

    left_text = _as_text(payload.get("left", "")).strip()
    right_text = _as_text(payload.get("right", "")).strip()

    left: Optional[Term] = None
    right: Optional[Term] = None
    try:
        left = parse(left_text)
    except ParseError as exc:
        issues.append(
            ValidationIssue("parse_error", f"左表达式语法错误：{exc}", "left")
        )
    try:
        right = parse(right_text)
    except ParseError as exc:
        issues.append(
            ValidationIssue("parse_error", f"右表达式语法错误：{exc}", "right")
        )

    for term, field_name in ((left, "left"), (right, "right")):
        if term is not None and node_count(term) > max_nodes:
            issues.append(
                ValidationIssue(
                    "node_limit",
                    f"{ '左' if field_name == 'left' else '右' }表达式含 "
                    f"{node_count(term)} 个节点，超过声明上限 {max_nodes}",
                    field_name,
                )
            )

    raw_rules = payload.get("rules", [])
    if raw_rules is None:
        raw_rules = []
    if not isinstance(raw_rules, (list, tuple)):
        issues.append(
            ValidationIssue("rules_shape", "规则必须以字符串数组形式提供", "rules")
        )
        raw_rules = []

    rule_texts = [_as_text(r).strip() for r in raw_rules if _as_text(r).strip()]
    if len(rule_texts) > MAX_RULES:
        issues.append(
            ValidationIssue(
                "too_many_rules",
                f"等式规则至多 {MAX_RULES} 条，当前收到 {len(rule_texts)} 条",
                "rules",
            )
        )

    rules = []
    rule_summaries: List[Dict[str, Any]] = []
    for idx, text in enumerate(rule_texts[:MAX_RULES], start=1):
        try:
            lhs, rhs = parse_rule(text)
        except ParseError as exc:
            issues.append(
                ValidationIssue(
                    "rule_parse_error", f"规则 {idx}（{text}）语法错误：{exc}",
                    f"rules[{idx - 1}]",
                )
            )
            continue
        rule_issue = False
        for side_name, side in (("左", lhs), ("右", rhs)):
            if node_count(side) > max_nodes:
                issues.append(
                    ValidationIssue(
                        "node_limit",
                        f"规则 {idx} 的{side_name}侧含 {node_count(side)} 个节点，"
                        f"超过声明上限 {max_nodes}",
                        f"rules[{idx - 1}]",
                    )
                )
                rule_issue = True
        if rule_issue:
            continue
        try:
            rule = make_rule(idx, lhs, rhs, text)
        except RuleError as exc:
            issues.append(
                ValidationIssue(
                    "unbound_variable", str(exc), f"rules[{idx - 1}]"
                )
            )
            continue
        rules.append(rule)
        rule_summaries.append(
            {
                "index": idx,
                "text": text,
                "lhs": canonical(lhs),
                "rhs": canonical(rhs),
                "bidirectional": True,
            }
        )

    summary = {
        "left": canonical(left) if left is not None else left_text,
        "right": canonical(right) if right is not None else right_text,
        "rule_count": len(rule_summaries),
        "rules": rule_summaries,
        "max_nodes": max_nodes,
        "max_applications": max_applications,
        "status_labels": STATUS_LABELS,
    }

    if issues:
        return {
            "status": INVALID,
            "status_text": STATUS_LABELS[INVALID],
            "summary": summary,
            "issues": [i.to_dict() for i in issues],
            # 无效时显式清空旧证据字段。
            "proof": None,
            "classes": None,
            "stats": None,
            "limit_reason": None,
        }

    assert left is not None and right is not None
    engine = Engine(
        rules=rules,
        max_nodes=max_nodes,
        max_applications=max_applications,
    )
    engine.run([left, right])

    stats = engine.stats()
    if not engine.saturated:
        return {
            "status": UNKNOWN,
            "status_text": STATUS_LABELS[UNKNOWN],
            "summary": summary,
            "issues": [],
            "proof": None,
            "classes": None,
            "stats": stats,
            "limit_reason": engine.limit_reason,
        }

    classes = engine.classes()
    stats["classes"] = len(classes)
    if engine.find(left) == engine.find(right):
        proof = _enrich_proof(engine, engine.proof(left, right))
        return {
            "status": EQUIVALENT,
            "status_text": STATUS_LABELS[EQUIVALENT],
            "summary": summary,
            "issues": [],
            "proof": proof,
            "classes": classes,
            "stats": stats,
            "limit_reason": None,
        }

    left_rep = canonical(engine.representative(left))
    right_rep = canonical(engine.representative(right))
    return {
        "status": NOT_EQUIVALENT,
        "status_text": STATUS_LABELS[NOT_EQUIVALENT],
        "summary": summary,
        "issues": [],
        "proof": None,
        "classes": classes,
        "left_class": left_rep,
        "right_class": right_rep,
        "stats": stats,
        "limit_reason": None,
    }


def _enrich_proof(
    engine: "Engine",
    steps: List[Any],
    _seen: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """把顶层步骤序列化，并为同余步骤递归附上参数等价的子证据。

    这样“逐步展开”时既能看到最终的同余合并，也能下钻到其依据的
    规则实例（如交换律在参数位置的应用）。前提是更小子项之间的
    证据，用已展开对集合防止异常成环。
    """

    from .parser import parse as _parse

    if _seen is None:
        _seen = set()
    result: List[Dict[str, Any]] = []
    for step in steps:
        node = step.to_dict()
        just = step.justification
        if just.kind == "congruence" and just.premises:
            children: List[Dict[str, Any]] = []
            for a_str, b_str in just.premises:
                if a_str == b_str:
                    continue
                key = (a_str, b_str)
                if key in _seen:
                    continue
                _seen.add(key)
                sub_steps = engine.proof(_parse(a_str), _parse(b_str))
                sub = _enrich_proof(engine, sub_steps, _seen)
                children.append({"from": a_str, "to": b_str, "steps": sub})
            if children:
                node["premise_proofs"] = children
        result.append(node)
    return result


def _coerce_limit(
    value: Any, default: int, field_name: str, issues: List[ValidationIssue]
) -> int:
    if value in (None, ""):
        return default
    try:
        result = int(value)
    except (TypeError, ValueError):
        issues.append(
            ValidationIssue(
                "bad_limit", f"上限参数 {field_name} 必须是非负整数", field_name
            )
        )
        return default
    if result <= 0:
        issues.append(
            ValidationIssue(
                "bad_limit", f"上限参数 {field_name} 必须为正整数", field_name
            )
        )
        return default
    return result
