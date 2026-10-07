"""受限表达式的词法/语法分析。

表达式文法（仅含具名常量与一元或二元函数调用）::

    expr   := NAME [ '(' expr [ ',' expr ] ')' ]
    NAME   := [A-Za-z_][A-Za-z0-9_]*

解析结果以 :class:`Term` 表示，等价于一棵定长子项树。
"""

from __future__ import annotations

from typing import List, Tuple


class ParseError(ValueError):
    """表达式或规则不符合受限文法。"""


class Term:
    """不可变项：叶子为常量/变量，内部节点为一元或二元函数调用。

    结构相等、可哈希；哈希值与结构签名在构造时缓存，供并查集与
    各类字典在深层树上反复使用时避免重复递归。
    """

    __slots__ = ("symbol", "args", "_hash", "_sig")

    def __init__(self, symbol: str, args: Tuple["Term", ...] = ()):
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "args", tuple(args))
        h = hash(symbol)
        for a in self.args:
            h ^= hash(a) + 0x9E3779B97F4A7C15 + (h << 6) + (h >> 3)
            h &= 0xFFFFFFFFFFFFFFFF
        object.__setattr__(self, "_hash", h)
        object.__setattr__(self, "_sig", None)

    @property
    def arity(self) -> int:
        return len(self.args)

    def __eq__(self, other: object) -> bool:
        if self is other:
            return True
        if not isinstance(other, Term):
            return NotImplemented
        return self.symbol == other.symbol and self.args == other.args

    def __hash__(self) -> int:
        return self._hash

    def __repr__(self) -> str:
        return f"Term({self.symbol!r}, {self.args!r})"

    def __str__(self) -> str:
        if not self.args:
            return self.symbol
        return f"{self.symbol}({', '.join(str(a) for a in self.args)})"

    @property
    def signature(self) -> str:
        """缓存的结构签名。"""

        if self._sig is None:
            if self.args:
                object.__setattr__(
                    self,
                    "_sig",
                    f"{self.symbol}({','.join(a.signature for a in self.args)})",
                )
            else:
                object.__setattr__(self, "_sig", self.symbol)
        return self._sig


_TOKEN_DIGITS = set("0123456789")
_TOKEN_START = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
)
_TOKEN_PART = _TOKEN_START | _TOKEN_DIGITS


def _tokenize(text: str) -> List[Tuple[str, str]]:
    tokens: List[Tuple[str, str]] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch in "(),":
            tokens.append((ch, ch))
            i += 1
            continue
        if ch in _TOKEN_START:
            j = i + 1
            while j < n and text[j] in _TOKEN_PART:
                j += 1
            tokens.append(("NAME", text[i:j]))
            i = j
            continue
        raise ParseError(f"非法字符 {ch!r}（位置 {i}）")
    tokens.append(("EOF", ""))
    return tokens


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.tokens = _tokenize(text)
        self.pos = 0

    @property
    def cur(self) -> Tuple[str, str]:
        return self.tokens[self.pos]

    def _advance(self) -> Tuple[str, str]:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def parse(self) -> Term:
        term = self._parse_term()
        if self.cur[0] != "EOF":
            raise ParseError(
                f"表达式在 {self._here()} 后仍有多余内容：{self.cur[1]!r}"
            )
        return term

    def _here(self) -> int:
        # 粗粒度位置信息，仅用于错误提示。
        return self.pos

    def _parse_term(self) -> Term:
        kind, value = self.cur
        if kind != "NAME":
            if kind == "EOF":
                raise ParseError("表达式不完整：意外的结束")
            raise ParseError(f"此处应为名称，却遇到 {value!r}")
        self._advance()
        if self.cur[0] != "(":
            return Term(value)
        self._advance()  # 吃掉 '('
        args: List[Term] = [self._parse_term()]
        if self.cur[0] == ",":
            self._advance()
            args.append(self._parse_term())
        if self.cur[0] != ")":
            if self.cur[0] == "EOF":
                raise ParseError("参数列表缺少右括号 ')'")
            if self.cur[0] == ",":
                raise ParseError("函数调用至多允许两个参数")
            raise ParseError(f"此处应为 ')'，却遇到 {self.cur[1]!r}")
        self._advance()
        return Term(value, tuple(args))


def parse(text: str) -> Term:
    """把受限表达式解析为 :class:`Term`。"""

    if text is None or not str(text).strip():
        raise ParseError("表达式为空")
    return _Parser(str(text)).parse()


def parse_rule(text: str) -> Tuple[Term, Term]:
    """解析 ``lhs = rhs`` 形式的等式规则。"""

    if "=" not in text:
        raise ParseError("规则必须形如 左式 = 右式")
    lhs_text, rhs_text = text.split("=", 1)
    if not lhs_text.strip() or not rhs_text.strip():
        raise ParseError("规则等号两侧均不能为空")
    return parse(lhs_text), parse(rhs_text)


def node_count(term: Term) -> int:
    """项的节点总数（含叶子）。"""

    return 1 + sum(node_count(a) for a in term.args)


def variables(term: Term) -> frozenset[str]:
    """收集规则中的*变量*叶子。

    约定：单个小写 ASCII 字母（``x``、``y``……）为全称量化变量，
    其余叶子（``zero``、``nil``、``a0``……）为必须字面匹配的具名
    常量。
    """

    if not term.args:
        return frozenset({term.symbol}) if is_variable_name(term.symbol) else frozenset()
    result: set[str] = set()
    for arg in term.args:
        result |= variables(arg)
    return frozenset(result)


def is_variable_name(name: str) -> bool:
    return len(name) == 1 and "a" <= name <= "z"


def substitute(term: Term, mapping: dict[str, Term]) -> Term:
    """把叶子名称按 ``mapping`` 替换为项。"""

    if not term.args:
        return mapping.get(term.symbol, term)
    return Term(
        term.symbol,
        tuple(substitute(a, mapping) for a in term.args),
    )


def signature(term: Term) -> str:
    """确定性的结构签名，供等价类摘要与哈希使用。"""

    return term.signature


def canonical(term: Term) -> str:
    """规范字符串。"""

    return term.signature
