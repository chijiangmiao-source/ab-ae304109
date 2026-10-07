"""验证服务：请求校验、规范摘要与结论装配。

结论四态：
  equivalent    —— 规则饱和后两式同属一个等价类，附逐步推导；
  inequivalent  —— 已饱和但分属不同等价类，只给稳定摘要，不带旧证据；
  incomplete    —— 达节点或应用次数上限仍未饱和；
  invalid       —— 语法错误、未绑定变量、超限规则/表达式，不带任何旧结论。

服务本身无状态：每次调用都构造并返回全新结果对象，调用方据此清除
页面上的旧证据。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .engine import DEFAULT_APPLICATION_LIMIT, DEFAULT_NODE_LIMIT, Engine
from .parser import ParseError, has_variables, iter_vars, node_count, parse
from .rules import MAX_RULES, RuleError, parse_rule

__all__ = ["SPEC_NODE_LIMIT", "verify_spec", "Invalid"]

SPEC_NODE_LIMIT = 80


@dataclass
class Invalid:
    status: str = "invalid"
    errors: list[dict] = field(default_factory=list)
    summary: dict | None = None


def _split_rules(raw_rules) -> list[str]:
    if raw_rules is None:
        return []
    if isinstance(raw_rules, str):
        return [line for line in raw_rules.splitlines() if line.strip()]
    if isinstance(raw_rules, (list, tuple)):
        return [str(r) for r in raw_rules]
    raise ValueError("rules 必须是字符串数组或按行分隔的字符串")


def verify_spec(payload: dict) -> dict:
    errors: list[dict] = []

    raw_left = payload.get("left", "")
    raw_right = payload.get("right", "")
    try:
        rule_lines = _split_rules(payload.get("rules", []))
    except ValueError as exc:
        rule_lines = []
        errors.append({"scope": "rules", "message": str(exc)})

    if len(rule_lines) > MAX_RULES:
        errors.append(
            {
                "scope": "rules",
                "message": f"等式规则至多 {MAX_RULES} 条，当前收到 {len(rule_lines)} 条",
            }
        )
        rule_lines = rule_lines[:MAX_RULES]

    def _positive_int(value, default: int, ceiling: int | None = None) -> int:
        try:
            num = int(value)
        except (TypeError, ValueError):
            errors.append(
                {"scope": "limits", "message": f"资源上限 {value!r} 不是整数"}
            )
            return default
        if num <= 0 or (ceiling is not None and num > ceiling):
            rng = f"1..{ceiling}" if ceiling is not None else "正整数"
            errors.append(
                {"scope": "limits", "message": f"资源上限必须为 {rng}：收到 {num}"}
            )
            return default
        return num

    node_limit = _positive_int(
        payload.get("node_limit", DEFAULT_NODE_LIMIT),
        DEFAULT_NODE_LIMIT, SPEC_NODE_LIMIT,
    )
    application_limit = _positive_int(
        payload.get("application_limit", DEFAULT_APPLICATION_LIMIT),
        DEFAULT_APPLICATION_LIMIT,
    )

    left = right = None
    for scope, raw in (("left", raw_left), ("right", raw_right)):
        try:
            term = parse(raw)
        except ParseError as exc:
            errors.append({"scope": scope, "message": str(exc)})
            continue
        if has_variables(term):
            names = sorted("?" + v for v in iter_vars(term))
            errors.append(
                {
                    "scope": scope,
                    "message": f"待判定表达式不得含未绑定变量：{', '.join(names)}",
                }
            )
            continue
        if node_count(term) > SPEC_NODE_LIMIT:
            errors.append(
                {
                    "scope": scope,
                    "message": f"表达式含 {node_count(term)} 个节点，"
                    f"超过声明的 {SPEC_NODE_LIMIT} 个节点上限",
                }
            )
            continue
        if scope == "left":
            left = term
        else:
            right = term

    rules = []
    for i, line in enumerate(rule_lines):
        try:
            rules.append(parse_rule(i, line, max_nodes=SPEC_NODE_LIMIT))
        except RuleError as exc:
            errors.append({"scope": "rule", "index": i, "message": str(exc)})

    summary = {
        "left": str(left) if left is not None else str(raw_left),
        "right": str(right) if right is not None else str(raw_right),
        "rules": [str(r) for r in rules],
        "rule_count": len(rules),
        "max_rules": MAX_RULES,
        "node_limit": node_limit,
        "application_limit": application_limit,
        "spec_node_limit": SPEC_NODE_LIMIT,
    }

    if errors:
        # 无效请求：不附带任何等价类或证据，调用方必须清除旧结论
        return asdict(Invalid(errors=errors, summary=summary))

    engine = Engine(
        rules, node_limit=node_limit, application_limit=application_limit
    )
    left_id = engine._intern(left, schedule=False)
    right_id = engine._intern(right, schedule=False)
    result = engine.run(left_id, right_id)
    out = asdict(result)
    out["summary"] = summary
    return out
