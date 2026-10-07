"""饱和式等式推导引擎。

做法：
  * 所有推导项哈希归一（structural interning），用并查集维护等价类；
  * 每条规则在每个已入林的项上做一阶语法匹配，把改写实例以确定顺序
    放入待合并队列；
  * 合并后按 Nelson-Oppen 同余闭包传播：参数等价则同函数名同元数的
    父项也等价（同余依据）；
  * 规则从两个方向尝试（反向要求模式能绑定左式全部变量）；
  * 只有在待合并队列与待枚举队列都排空（饱和）后才判定等价；
  * 触发节点上限或规则应用次数上限而尚未饱和 => 未完成。

整个引擎单线程使用，所有队列均为确定的 FIFO 顺序。
"""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass

from .parser import Term, iter_vars, node_count
from .rules import Rule

__all__ = [
    "RuleStep",
    "Congruence",
    "Equivalent",
    "Inequivalent",
    "Incomplete",
    "Engine",
]

# 默认资源声明
DEFAULT_NODE_LIMIT = 80
DEFAULT_APPLICATION_LIMIT = 5_000


@dataclass(frozen=True)
class RuleStep:
    """一次规则实例化改写（整个顶层项 before -> after）。"""

    kind: str = "rule"
    rule_index: int = 0
    rule_text: str = ""
    path: tuple[int, ...] = ()
    bindings: tuple[tuple[str, str], ...] = ()
    redex_before: str = ""
    redex_after: str = ""
    a: int = 0
    b: int = 0


@dataclass(frozen=True)
class Congruence:
    """同余闭包产生的合并：参数逐项等价故父项等价。"""

    kind: str = "congruence"
    func: str = ""
    arity: int = 0
    a: int = 0
    b: int = 0


@dataclass(frozen=True)
class DerivationStep:
    kind: str
    reversed_edge: bool
    before: str
    after: str
    detail: dict


@dataclass
class ClassSummary:
    representative: str
    members: list[str]
    fingerprint: str


@dataclass
class Equivalent:
    status: str
    derivation: list[DerivationStep]
    classes: list[ClassSummary]
    fingerprint: str
    applications: int
    nodes: int


@dataclass
class Inequivalent:
    status: str
    classes: list[ClassSummary]
    fingerprint: str
    applications: int
    nodes: int


@dataclass
class Incomplete:
    status: str
    reason: str
    applications: int
    nodes: int
    node_limit: int
    application_limit: int
    message: str


# ---------------------------------------------------------------------------
# 一阶语法匹配与替换
# ---------------------------------------------------------------------------


def _match(pattern: Term, subject: Term, subst: dict[str, Term]) -> bool:
    """把 pattern 一阶语法匹配到 ground 项 subject。

    pattern 中的变量叶子（is_var）绑定到任意子项；具名常量与函数名、
    元数必须逐字相等。subject 不允许含变量。
    """
    if pattern.kind == 0 and pattern.is_var:
        old = subst.get(pattern.name)
        if old is None:
            subst[pattern.name] = subject
            return True
        return old == subject
    if subject.kind != pattern.kind or subject.name != pattern.name:
        return False
    if len(pattern.args) != len(subject.args):
        return False
    for pa, sa in zip(pattern.args, subject.args):
        if not _match(pa, sa, subst):
            return False
    return True


def _substitute(term: Term, subst: dict[str, Term]) -> Term:
    if term.kind == 0:
        return subst.get(term.name, term) if term.is_var else term
    return Term(term.kind, term.name, tuple(_substitute(a, subst) for a in term.args))


def _replace_at(term: Term, path: tuple[int, ...], repl: Term) -> Term:
    if not path:
        return repl
    i = path[0]
    new_args = list(term.args)
    new_args[i] = _replace_at(new_args[i], path[1:], repl)
    return Term(term.kind, term.name, tuple(new_args))


def _subterms(term: Term, prefix: tuple[int, ...] = ()):
    yield prefix, term
    for i, arg in enumerate(term.args):
        yield from _subterms(arg, prefix + (i,))


def term_key(term: Term):
    """结构全序：用于确定性的代表元与稳定摘要。"""
    return (term.kind, term.name, tuple(term_key(a) for a in term.args))


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------


class Engine:
    def __init__(
        self,
        rules: list[Rule],
        node_limit: int = DEFAULT_NODE_LIMIT,
        application_limit: int = DEFAULT_APPLICATION_LIMIT,
    ) -> None:
        self.rules = rules
        self.node_limit = node_limit
        self.application_limit = application_limit

        # 哈希一致的项林
        self._id_by_term: dict[Term, int] = {}
        self._term_by_id: list[Term] = []
        self._children: list[tuple[int, ...]] = []

        # 并查集
        self._uf: list[int] = []
        self._rank: list[int] = []
        # 每个代表元上的“使用者”（以它为参数的父项 id）
        self._users: list[list[int]] = []
        # 合并证据：挂在规则/同余实际涉及的两个操作数上
        self._proof_edges: list[list[tuple[int, int, object]]] = []
        # 同余签名索引：signature -> 某个持有该签名的父项 id
        self._sig_index: dict = {}

        self._pending: deque[tuple[int, int, object]] = deque()
        self._worklist: deque[int] = deque()
        self._enumerated: set[int] = set()

        self.applications = 0
        self.overflow = False

    # --  interning / union-find  ----------------------------------------

    def _intern(self, term: Term, schedule: bool) -> int:
        existing = self._id_by_term.get(term)
        if existing is not None:
            return existing
        child_ids = tuple(self._intern(a, schedule) for a in term.args)
        tid = len(self._term_by_id)
        self._id_by_term[term] = tid
        self._term_by_id.append(term)
        self._children.append(child_ids)
        self._uf.append(tid)
        self._rank.append(0)
        self._users.append([])
        self._proof_edges.append([])
        for cid in child_ids:
            self._users[self._find(cid)].append(tid)
        if term.kind != 0:
            sig = self._signature(tid)
            anchor = self._sig_index.get(sig)
            if anchor is not None and self._signature(anchor) == sig:
                self._pending.append(
                    (
                        anchor,
                        tid,
                        Congruence(func=term.name, arity=term.kind, a=anchor, b=tid),
                    )
                )
            else:
                self._sig_index[sig] = tid
        if schedule:
            self._worklist.append(tid)
        return tid

    def _find(self, x: int) -> int:
        uf = self._uf
        root = x
        while uf[root] != root:
            root = uf[root]
        while uf[x] != x:
            uf[x], x = root, uf[x]
        return root

    def _signature(self, tid: int):
        term = self._term_by_id[tid]
        if term.kind == 0:
            return (0, term.name)
        return (term.kind, term.name, tuple(self._find(c) for c in self._children[tid]))

    def _union(self, a: int, b: int, reason: object) -> bool:
        ra = self._find(a)
        rb = self._find(b)
        if ra == rb:
            return False
        # 证据挂在实际操作数上（方向 a -> b 与叙述一致）
        self._proof_edges[a].append((a, b, reason))
        self._proof_edges[b].append((b, a, reason))

        # 按秩合并；合并成员、使用者与签名索引
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._uf[rb] = ra
        self._users[ra].extend(self._users[rb])
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1

        # 合并两个旧类上的签名桶，再在合并后的类内做同余配对
        buckets: dict = {}
        for pid in set(self._users[ra]):
            sig = self._signature(pid)
            buckets.setdefault(sig, []).append(pid)
        for sig, pids in buckets.items():
            first = self._sig_index.get(sig)
            if first is not None and self._signature(first) == sig and first not in pids:
                pids.insert(0, first)
            ordered = sorted(set(pids))
            if ordered:
                self._sig_index[sig] = ordered[0]
            anchor = ordered[0]
            for pid in ordered[1:]:
                term = self._term_by_id[pid]
                self._pending.append(
                    (
                        anchor,
                        pid,
                        Congruence(
                            func=term.name,
                            arity=term.kind,
                            a=anchor,
                            b=pid,
                        ),
                    )
                )
        return True

    # -- 规则枚举 ----------------------------------------------------------

    def _enumerate(self, tid: int) -> str | None:
        """对一个项的全部子项按规则顺序生成改写实例。

        规则在子项（redex）上实例化：只合并 redex 两侧（规则证据），
        外层上下文的等价由同余闭包自动传播（同余证据），因此等价推导
        能逐步区分“规则实例”与“同余依据”。
        """
        top = self._term_by_id[tid]
        for path, sub in _subterms(top):
            sub_id = self._intern(sub, schedule=False)
            for rule in self.rules:
                for pattern, replacement_tmpl, is_reverse in (
                    (rule.lhs, rule.rhs, False),
                    (rule.rhs, rule.lhs, True),
                ):
                    subst: dict[str, Term] = {}
                    if not _match(pattern, sub, subst):
                        continue
                    if is_reverse:
                        unbound = sorted(iter_vars(replacement_tmpl) - set(subst))
                        if unbound:
                            # 反向实例化无法猜测这些变量的取值，跳过
                            continue
                        if rule.rhs.kind == 0 and rule.rhs.is_var:
                            # 反向把任意项展成含构造器的实例（如单位律
                            # add(ZERO,?x)=?x 的反向），项宇宙无穷，跳过
                            continue
                    new_redex = _substitute(replacement_tmpl, subst)
                    if new_redex == sub:
                        continue
                    new_top = new_redex if not path else _replace_at(top, path, new_redex)
                    if node_count(new_top) > self.node_limit:
                        # 任一推导项不得超过声明的节点上限
                        self.overflow = True
                        continue
                    if self.applications >= self.application_limit:
                        return "application_limit"
                    self.applications += 1
                    # 入林新项（含上下文外层），随后仅合并 redex 对；
                    # 同余闭包负责把外层上下文两两合并。
                    self._intern(new_top, schedule=True)
                    redex_id = self._intern(new_redex, schedule=True)
                    bindings = tuple(
                        sorted(("?" + v, str(t)) for v, t in subst.items())
                    )
                    step = RuleStep(
                        rule_index=rule.index,
                        rule_text=rule.raw,
                        path=path,
                        bindings=bindings,
                        redex_before=str(sub),
                        redex_after=str(new_redex),
                        a=sub_id,
                        b=redex_id,
                    )
                    self._pending.append((sub_id, redex_id, step))
        return None

    # -- 主循环 -------------------------------------------------------------

    def run(self, left_id: int, right_id: int):
        for seed in (left_id, right_id):
            if seed not in self._enumerated:
                self._worklist.append(seed)
        while self._pending or self._worklist:
            if self._pending:
                a, b, reason = self._pending.popleft()
                self._union(a, b, reason)
                continue
            tid = self._worklist.popleft()
            if tid in self._enumerated:
                continue
            self._enumerated.add(tid)
            if self._enumerate(tid) == "application_limit":
                return Incomplete(
                    status="incomplete",
                    reason="application_limit",
                    applications=self.applications,
                    nodes=len(self._term_by_id),
                    node_limit=self.node_limit,
                    application_limit=self.application_limit,
                    message=(
                        f"已达到规则应用次数上限 {self.application_limit}，"
                        "改写队列尚未排空，无法判定等价性"
                    ),
                )

        if self.overflow:
            return Incomplete(
                status="incomplete",
                reason="node_limit",
                applications=self.applications,
                nodes=len(self._term_by_id),
                node_limit=self.node_limit,
                application_limit=self.application_limit,
                message=(
                    f"继续改写将产生超过 {self.node_limit} 个节点的推导项，"
                    "在节点上限内无法饱和，无法判定等价性"
                ),
            )

        if self._find(left_id) != self._find(right_id):
            return self._inequivalent()
        return self._equivalent(left_id, right_id)

    # -- 结论构造 -----------------------------------------------------------

    def _class_summaries(self) -> tuple[list[ClassSummary], str]:
        groups: dict[int, list[Term]] = {}
        for tid, term in enumerate(self._term_by_id):
            groups.setdefault(self._find(tid), []).append(term)
        summaries: list[ClassSummary] = []
        for members in groups.values():
            ordered = sorted(members, key=term_key)
            rep = ordered[0]
            summaries.append(
                ClassSummary(
                    representative=str(rep),
                    members=[str(t) for t in ordered],
                    fingerprint="",
                )
            )
        summaries.sort(key=lambda c: c.representative)
        canonical = "\n".join(
            " | ".join(c.members) for c in summaries
        )
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        for c in summaries:
            c.fingerprint = fingerprint
        return summaries, fingerprint

    def _inequivalent(self) -> Inequivalent:
        classes, fp = self._class_summaries()
        return Inequivalent(
            status="inequivalent",
            classes=classes,
            fingerprint=fp,
            applications=self.applications,
            nodes=len(self._term_by_id),
        )

    def _proof_path(self, src: int, dst: int):
        """在操作数证据图上做确定性 BFS。

        每次成功合并都在两个操作数间留一条无向证据边；最终等价类恰由
        这些边的传递闭包构成，因此 src~dst 时必有路径。
        返回 [(x, y, reason), ...]，方向为路径遍历方向。
        """
        def edge_key(entry: tuple[int, int, object]):
            _x, y, reason = entry
            if reason.kind == "rule":
                return (0, reason.rule_index, y)
            return (1, reason.func, reason.arity, y)

        prev: dict[int, tuple[int, object]] = {src: (-1, None)}  # type: ignore[dict-item]
        queue = deque([src])
        while queue:
            cur = queue.popleft()
            if cur == dst:
                break
            for x, y, reason in sorted(self._proof_edges[cur], key=edge_key):
                if y not in prev:
                    prev[y] = (cur, reason)
                    queue.append(y)
        if dst not in prev:
            return []
        chain = []
        node = dst
        while node != src:
            parent, reason = prev[node]
            chain.append((parent, node, reason))
            node = parent
        chain.reverse()
        return chain

    def _explain(self, src: int, dst: int, active: frozenset = frozenset()):
        """展开 src => dst：规则步骤平铺；同余步骤嵌套展开参数子证明。"""
        chain = self._proof_path(src, dst)
        steps: list[DerivationStep] = []
        pair_key = (src, dst)
        nested = active | {pair_key}
        for x, nxt, reason in chain:
            before = self._term_by_id[x]
            after = self._term_by_id[nxt]
            if reason.kind == "rule":
                reverse = x == reason.b and nxt == reason.a
                path_text = (
                    "顶层"
                    if not reason.path
                    else "参数 " + " → ".join(str(i + 1) for i in reason.path)
                )
                detail = {
                    "rule_index": reason.rule_index + 1,
                    "rule_text": reason.rule_text,
                    "applied_direction": "反向" if reverse else "正向",
                    "path": path_text,
                    "bindings": [
                        {"var": v, "term": t} for v, t in reason.bindings
                    ],
                    "redex_before": reason.redex_before,
                    "redex_after": reason.redex_after,
                }
            else:
                child_basis = []
                for i, (cx, cy) in enumerate(
                    zip(self._children[x], self._children[nxt])
                ):
                    tx, ty = self._term_by_id[cx], self._term_by_id[cy]
                    if tx == ty:
                        continue
                    entry = {
                        "position": i + 1,
                        "left": str(tx),
                        "right": str(ty),
                    }
                    # 嵌套给出该参数对的等价推导（规则实例在此出现）
                    if self._find(cx) == self._find(cy) and (cx, cy) not in nested:
                        entry["derivation"] = self._explain(cx, cy, nested)
                    child_basis.append(entry)
                reverse = False
                detail = {
                    "rule_index": None,
                    "rule_text": None,
                    "applied_direction": "同余",
                    "path": f"函数 {reason.func}/{reason.arity} 的参数等价",
                    "child_basis": child_basis,
                }
            steps.append(
                DerivationStep(
                    kind=reason.kind,
                    reversed_edge=reverse,
                    before=str(before),
                    after=str(after),
                    detail=detail,
                )
            )
        return steps

    def _equivalent(self, left_id: int, right_id: int) -> Equivalent:
        steps = self._explain(left_id, right_id)
        classes, fp = self._class_summaries()
        return Equivalent(
            status="equivalent",
            derivation=steps,
            classes=classes,
            fingerprint=fp,
            applications=self.applications,
            nodes=len(self._term_by_id),
        )
