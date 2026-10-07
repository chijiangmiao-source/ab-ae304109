"""同余闭包 + 等式重写的饱和引擎。

设计要点
========

* 以并查集维护等价类；类的代表元固定为**最小结构签名**对应项，
  因此摘要与哈希在合并过程中稳定、确定。
* 同余闭包：两个调用符号相同且参数逐对等价时自动合并。合并后把
  受影响调用按确定顺序投入 FIFO *待重建队列* 重新计算签名；
  同余表按签名保存全部成员并随重建实时迁移，杜绝陈旧签名误并。
* 规则：等式规则两侧都登记，双向匹配；规则右式不得引入左式未
  出现的变量（见 :func:`make_rule`）。规则中的叶子标识符一律视
  为全称量化的模式变量。
* 仅在待合并队列与待重建队列均清空、且一整轮规则扫描不再产生
  任何新项或新合并（*饱和*）之后，才作等价判断。
* 资源边界：任一推导项节点数超过 ``max_nodes``（声明 80）或
  规则有效应用次数超过 ``max_applications`` 而尚未饱和 ⇒
  结论为“未完成”。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, List, Optional, Set, Tuple

from .parser import (
    Term,
    canonical,
    is_variable_name,
    node_count,
    substitute,
    variables,
)

DEFAULT_MAX_NODES = 80
DEFAULT_MAX_APPLICATIONS = 5_000


class RuleError(ValueError):
    """规则语义不合法（语法错误由 ParseError 表达）。"""


@dataclass(frozen=True)
class Rule:
    """一条已校验的等式规则 ``lhs = rhs``。"""

    index: int
    lhs: Term
    rhs: Term
    text: str

    @property
    def safely_reversible(self) -> bool:
        """能否无歧义地反向应用。

        正向要求 ``vars(rhs) ⊆ vars(lhs)``（校验保证）。反向模式是
        ``rhs``、替换目标是 ``lhs``；只有当 ``vars(lhs) ⊆ vars(rhs)``
        （即两侧变量集相同）时，反向匹配才能为目标中的每个变量都
        提供绑定。否则如 ``g(x) = c`` 反向会凭空捏造 ``x``，故禁止。
        """

        return variables(self.lhs) <= variables(self.rhs)

    @property
    def sides(self) -> Tuple[Tuple[Term, Term, str], ...]:
        forward = (self.lhs, self.rhs, "→")
        reverse = (self.rhs, self.lhs, "←")
        return (forward, reverse) if self.safely_reversible else (forward,)


def make_rule(index: int, lhs: Term, rhs: Term, text: str) -> Rule:
    extra = variables(rhs) - variables(lhs)
    if extra:
        raise RuleError(
            f"规则 {text!r} 右侧引入了左侧未出现的变量："
            + ", ".join(sorted(extra))
        )
    return Rule(index=index, lhs=lhs, rhs=rhs, text=text)


@dataclass(frozen=True)
class Justification:
    """等价关系的来源依据。"""

    kind: str  # 'rule' | 'congruence'
    rule_index: Optional[int] = None
    rule_text: Optional[str] = None
    direction: Optional[str] = None
    substitution: Optional[Dict[str, str]] = None
    detail: Optional[str] = None
    # 同余依据的前提：逐对等价的参数（规范串）
    premises: Optional[Tuple[Tuple[str, str], ...]] = None

    def reversed(self) -> "Justification":
        direction = self.direction
        if direction == "→":
            direction = "←"
        elif direction == "←":
            direction = "→"
        return Justification(
            kind=self.kind,
            rule_index=self.rule_index,
            rule_text=self.rule_text,
            direction=direction,
            substitution=dict(self.substitution or {}),
            detail=("（反向依据）" + self.detail) if self.detail else None,
            premises=tuple((b, a) for a, b in self.premises)
            if self.premises
            else None,
        )

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "rule_index": self.rule_index,
            "rule_text": self.rule_text,
            "direction": self.direction,
            "substitution": dict(self.substitution or {}),
            "detail": self.detail,
            "premises": [list(p) for p in (self.premises or ())],
        }


@dataclass(frozen=True)
class Step:
    frm: str
    to: str
    justification: Justification

    def to_dict(self) -> dict:
        return {
            "from": self.frm,
            "to": self.to,
            "by": self.justification.to_dict(),
        }


@dataclass(frozen=True)
class _MergeRecord:
    a: Term
    b: Term
    justification: Justification


@dataclass
class Engine:
    """对一组固定输入运行的饱和引擎（一次性，不可复用）。"""

    rules: List[Rule]
    max_nodes: int = DEFAULT_MAX_NODES
    max_applications: int = DEFAULT_MAX_APPLICATIONS

    _parent: Dict[Term, Term] = field(default_factory=dict)
    _root_repr: Dict[Term, Term] = field(default_factory=dict)
    # 并查集根 -> 该类当前全部成员（合并时取并集）
    _class_terms: Dict[Term, Set[Term]] = field(default_factory=dict)
    # 参数项 -> 以其为直接参数的调用集合（同余传播用）
    _parents: Dict[Term, Set[Term]] = field(default_factory=dict)
    # 调用项当前签名
    _sig_of: Dict[Term, Tuple[str, Tuple[str, ...]]] = field(default_factory=dict)
    # 同余签名 -> 具备该签名的调用（保持规范串有序）
    _congruence: Dict[Tuple[str, Tuple[str, ...]], List[Term]] = field(
        default_factory=dict
    )

    _pending: Deque[_MergeRecord] = field(default_factory=deque)
    _rebuild: Deque[Term] = field(default_factory=deque)
    _rebuild_seen: Set[Term] = field(default_factory=set)

    _history: List[_MergeRecord] = field(default_factory=list)
    _all_terms: Set[Term] = field(default_factory=set)

    applications: int = 0
    rounds: int = 0
    saturated: bool = True
    limit_reason: Optional[str] = None

    # ------------------------------------------------------------------
    # 登记与并查集
    # ------------------------------------------------------------------
    def _intern(self, term: Term) -> Term:
        """登记项及其子树，返回该项的规范（已登记）对象。

        :class:`Term` 按结构相等，两个同值对象可能先后出现；统一以
        首次登记者为准并递归归一化参数，保证并查集与父项表里出现
        的永远是同一对象，``is`` 比较因此可靠。
        """

        existing = self._parent.get(term)
        if existing is not None:
            return existing
        canonical_args = tuple(self._intern(a) for a in term.args)
        normalized = (
            term if not term.args or all(
                a is b for a, b in zip(term.args, canonical_args)
            ) else Term(term.symbol, canonical_args)
        )
        # 归一化后可能恰好与某个既有项同值（罕见竞态）。
        existing = self._parent.get(normalized)
        if existing is not None:
            return existing
        self._parent[normalized] = normalized
        self._root_repr[normalized] = normalized
        self._all_terms.add(normalized)
        self._class_terms[normalized] = {normalized}
        for arg in canonical_args:
            self._parents.setdefault(arg, set()).add(normalized)
        if normalized.args:
            sig = self._compute_sig(normalized)
            self._sig_of[normalized] = sig
            self._congruence.setdefault(sig, []).append(normalized)
            # 新登记调用可能与既有调用同签名（参数已同类）。
            self._congruence_collisions(normalized)
        return normalized

    def find(self, term: Term) -> Term:
        root = term
        while self._parent[root] != root:
            root = self._parent[root]
        node = term
        while self._parent[node] != node:
            nxt = self._parent[node]
            self._parent[node] = root
            node = nxt
        return root

    def representative(self, term: Term) -> Term:
        return self._root_repr[self.find(term)]

    def _compute_sig(self, term: Term) -> Tuple[str, Tuple[str, ...]]:
        return (
            term.symbol,
            tuple(canonical(self._root_repr[self.find(a)]) for a in term.args),
        )

    # ------------------------------------------------------------------
    # 同余表迁移与待重建队列
    # ------------------------------------------------------------------
    def _congruence_collisions(self, term: Term) -> None:
        """检查 ``term`` 与同签名的其他成员，异则入待合并队列。"""

        sig = self._sig_of[term]
        members = self._congruence[sig]
        for other in sorted(members, key=canonical):
            if other is term:
                continue
            if self.find(other) != self.find(term):
                premises = tuple(
                    (canonical(oa), canonical(ta))
                    for oa, ta in zip(other.args, term.args)
                )
                self._pending.append(
                    _MergeRecord(
                        other,
                        term,
                        Justification(
                            kind="congruence",
                            detail=(
                                "同余："
                                f"{canonical(other)} 与 {canonical(term)} "
                                "函数符号相同且各参数分别等价"
                            ),
                            premises=premises,
                        ),
                    )
                )

    def _enqueue_rebuild(self, affected_calls: Iterable[Term]) -> None:
        for call in sorted(affected_calls, key=canonical):
            if call not in self._rebuild_seen:
                self._rebuild_seen.add(call)
                self._rebuild.append(call)

    def _process_rebuild(self) -> None:
        while self._rebuild:
            term = self._rebuild.popleft()
            self._rebuild_seen.discard(term)
            if not term.args:
                continue
            old_sig = self._sig_of.get(term)
            new_sig = self._compute_sig(term)
            if old_sig == new_sig:
                continue
            if old_sig is not None:
                bucket = self._congruence.get(old_sig)
                if bucket is not None:
                    # 恒等删除（可能含同构重复项）。
                    for i, member in enumerate(bucket):
                        if member is term:
                            del bucket[i]
                            break
                    if not bucket:
                        del self._congruence[old_sig]
            self._sig_of[term] = new_sig
            new_bucket = self._congruence.setdefault(new_sig, [])
            new_bucket.append(term)
            new_bucket.sort(key=canonical)
            self._congruence_collisions(term)

    # ------------------------------------------------------------------
    # 合并
    # ------------------------------------------------------------------
    def _merge(self, record: _MergeRecord) -> None:
        ra, rb = self.find(record.a), self.find(record.b)
        if ra == rb:
            return
        rep_a, rep_b = self._root_repr[ra], self._root_repr[rb]
        # 固定代表：按 (节点数, 结构签名) 取最小，保证稳定且尽量小，
        # 从而哈希/摘要一致、变量实例化不产生虚胖项。
        if _rank(rep_a) <= _rank(rep_b):
            keep, drop, keep_rep, drop_rep = ra, rb, rep_a, rep_b
        else:
            keep, drop, keep_rep, drop_rep = rb, ra, rep_b, rep_a

        # 受影响调用 = drop 类中每个成员作为“直接参数”的父调用。
        affected: Set[Term] = set()
        for member in tuple(self._class_terms.get(drop, ())):
            affected.update(self._parents.get(member, ()))

        self._parent[drop] = keep
        self._root_repr[keep] = keep_rep
        del self._root_repr[drop]
        # 合并成员集合并迁移到新根。
        kept_members = self._class_terms.pop(drop)
        self._class_terms[keep].update(kept_members)
        # 证据图以*见证项*（规则的两端或同余的一对调用）为边，
        # 其连通分量与并查集的合并严格对应，可还原任意同类两点。
        self._history.append(
            _MergeRecord(record.a, record.b, record.justification)
        )
        self._enqueue_rebuild(affected)

    def _drain(self) -> None:
        """排空“待合并 ↔ 待重建”闭包，直到双双为空。"""

        while self._pending or self._rebuild:
            while self._pending:
                record = self._pending.popleft()
                self._intern(record.a)
                self._intern(record.b)
                self._merge(record)
            self._process_rebuild()

    # ------------------------------------------------------------------
    # 规则匹配（叶子即模式变量，匹配任意项）
    # ------------------------------------------------------------------
    def _match(
        self, pattern: Term, subject: Term, env: Dict[str, Term]
    ) -> Optional[Dict[str, Term]]:
        if not pattern.args:
            if not is_variable_name(pattern.symbol):
                # 具名常量：只匹配同符号叶子。
                if (
                    not subject.args
                    and subject.symbol == pattern.symbol
                ):
                    return env
                return None
            # 变量绑定到所属等价类的稳定代表元（最小项），
            # 避免用类中的冗余大成员实例化出虚胖的瞬态项。
            subject_rep = self.representative(subject)
            bound = env.get(pattern.symbol)
            if bound is None:
                env = dict(env)
                env[pattern.symbol] = subject_rep
                return env
            return env if self.find(bound) == self.find(subject_rep) else None
        if (
            not subject.args
            or pattern.symbol != subject.symbol
            or len(pattern.args) != len(subject.args)
        ):
            return None
        for pa, sa in zip(pattern.args, subject.args):
            env = self._match(pa, sa, env)
            if env is None:
                return None
        return env

    def _subjects_for(self, pattern: Term) -> List[Term]:
        ordered = sorted(self._all_terms, key=canonical)
        if not pattern.args:
            # 叶子模式可匹配任意形态的项，逐类成员都要尝试。
            return ordered
        return [
            t
            for t in ordered
            if t.args
            and t.symbol == pattern.symbol
            and len(t.args) == len(pattern.args)
        ]

    def _register_instance(
        self,
        instance: Term,
        matched: Term,
        rule: Rule,
        direction: str,
        env: Dict[str, Term],
    ) -> bool:
        """登记规则实例并入队合并；返回是否产生了新信息。"""

        novel = False
        canonical_instance = self._intern(instance)
        if self.find(matched) != self.find(canonical_instance):
            self._pending.append(
                _MergeRecord(
                    matched,
                    canonical_instance,
                    Justification(
                        kind="rule",
                        rule_index=rule.index,
                        rule_text=rule.text,
                        direction=direction,
                        substitution={
                            k: canonical(v) for k, v in sorted(env.items())
                        },
                        detail=(
                            f"应用规则 {rule.text}（{direction}），"
                            f"得 {canonical(matched)} ≈ {canonical(instance)}"
                        ),
                    ),
                )
            )
            novel = True
        return novel

    def _apply_rules(self) -> bool:
        """一整轮双向规则扫描；返回是否产生新信息。"""

        progressed = False
        for rule in self.rules:
            for pattern, template, direction in rule.sides:
                for subject in self._subjects_for(pattern):
                    env = self._match(pattern, subject, {})
                    if env is None:
                        continue
                    instance = substitute(template, env)
                    count = node_count(instance)
                    if count > self.max_nodes:
                        self.saturated = False
                        self.limit_reason = (
                            f"规则 {rule.text!r} 的实例 "
                            f"{canonical(instance)} 含 {count} 个节点，"
                            f"超过声明上限 {self.max_nodes}"
                        )
                        return False
                    if self._register_instance(
                        instance, subject, rule, direction, env
                    ):
                        progressed = True
                        self.applications += 1
                        if self.applications > self.max_applications:
                            self.saturated = False
                            self.limit_reason = (
                                "规则有效应用次数达到上限 "
                                f"{self.max_applications}，闭包尚未饱和"
                            )
                            return False
                        # 立即传播，可让后续匹配看到最新等价类，
                        # 同时保持处理顺序确定（FIFO）。
                        self._drain()
        return progressed

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    def run(self, seeds: Iterable[Term]) -> None:
        for seed in sorted(set(seeds), key=canonical):
            self._intern(seed)
        self._drain()  # 种子之间初始同余
        while self.saturated:
            progressed = self._apply_rules()
            if not self.saturated:
                return
            merges_before = len(self._history)
            self._drain()
            drained_merges = len(self._history) - merges_before
            self.rounds += 1
            # 仅当一整轮规则扫描零新增、且排空阶段也未产生新合并时，
            # 待合并/待重建队列方才真正为空 ⇒ 饱和。
            if not progressed and drained_merges == 0:
                return

    # ------------------------------------------------------------------
    # 结论与摘要
    # ------------------------------------------------------------------
    def classes(self) -> List[Dict[str, object]]:
        groups: Dict[Term, List[Term]] = {}
        for term in self._all_terms:
            groups.setdefault(self.find(term), []).append(term)
        result: List[Dict[str, object]] = []
        for root, members in groups.items():
            member_strings = sorted({canonical(m) for m in members})
            result.append(
                {
                    "representative": canonical(self._root_repr[root]),
                    "members": member_strings,
                    "size": len(member_strings),
                    "digest": digest_strings(member_strings),
                }
            )
        result.sort(key=lambda c: str(c["representative"]))
        return result

    def stats(self) -> Dict[str, int]:
        return {
            "terms": len(self._all_terms),
            "rule_applications": self.applications,
            "rounds": self.rounds,
            "merge_events": len(self._history),
        }

    def proof(self, left: Term, right: Term) -> List[Step]:
        """在合并历史无向图上以 BFS 还原 left→right 的依据链。"""

        adjacency: Dict[str, List[Tuple[str, Step]]] = {}

        def add_edge(x: Term, y: Term, just: Justification) -> None:
            xs, ys = canonical(x), canonical(y)
            if xs == ys:
                return
            adjacency.setdefault(xs, []).append((ys, Step(xs, ys, just)))
            adjacency.setdefault(ys, []).append(
                (xs, Step(ys, xs, just.reversed()))
            )

        for rec in self._history:
            add_edge(rec.a, rec.b, rec.justification)

        start, goal = canonical(left), canonical(right)
        return _bfs_path(adjacency, start, goal)


def _bfs_path(
    adjacency: Dict[str, List[Tuple[str, Step]]], start: str, goal: str
) -> List[Step]:
    if start == goal:
        return []
    parent: Dict[str, Tuple[str, Step]] = {}
    seen = {start}
    queue: Deque[str] = deque([start])
    while queue:
        node = queue.popleft()
        for nxt, step in sorted(adjacency.get(node, ()), key=lambda p: p[0]):
            if nxt in seen:
                continue
            seen.add(nxt)
            parent[nxt] = (node, step)
            if nxt == goal:
                break
            queue.append(nxt)
    if goal not in parent:
        return []
    path: List[Step] = []
    cur = goal
    while cur != start:
        prev, step = parent[cur]
        path.append(step)
        cur = prev
    path.reverse()
    return path


def _rank(term: Term) -> Tuple[int, str]:
    """稳定代表元排名：先比节点数（小者优先），再比规范串。

    保证等价类中若含叶子，代表元必为叶子，避免变量实例化时以深层
    复合项为代表而产生虚胖的新项。
    """

    return (node_count(term), canonical(term))


def digest_strings(values: List[str]) -> str:
    """成员列表的确定性 64 位摘要（FNV-1a）。"""

    data = "\x00".join(values).encode("utf-8")
    h = 0xCBF29CE484222325
    for byte in data:
        h ^= byte
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"
