"""AST 定义与递归下降解析器。

语法：
    expr := head [ "(" expr ("," expr)? ")" ]
    head := IDENT（具名常量/函数名） | VAR（规则变量）
    顶层仅允许一个完整表达式（末尾不允许多余 token）。

约定：
  * kind=0 的叶子若 is_var 为真则是规则变量 ?name；否则是具名常量；
  * 函数名必须是裸标识符（不能用变量当函数）。
"""

from __future__ import annotations

from dataclasses import dataclass

from .lexer import LexerError, Token, TokenKind, tokenize

__all__ = ["Term", "parse", "ParseError", "node_count", "iter_vars", "has_variables"]


@dataclass(frozen=True)
class Term:
    """哈希一致的不可变表达式节点。

    叶子: kind=0, name=常量/变量名（不含问号前缀）, is_var=True 表示变量
    复合: kind=1（一元）或 2（二元），name=函数名，is_var=False
    """

    kind: int
    name: str
    args: tuple["Term", ...] = ()
    is_var: bool = False

    def __str__(self) -> str:
        if self.kind == 0:
            return f"?{self.name}" if self.is_var else self.name
        return f"{self.name}({', '.join(map(str, self.args))})"


class ParseError(ValueError):
    pass


@dataclass
class _Parser:
    tokens: list[Token]
    pos: int = 0

    def _peek(self) -> Token:
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def parse_expr(self) -> Term:
        tok = self._peek()
        if tok.kind not in (TokenKind.IDENT, TokenKind.VAR):
            raise ParseError(
                f"语法错误（位置 {tok.pos}）：应为标识符、变量或函数调用，"
                f"却遇到 {tok.value!r}"
            )
        if tok.kind == TokenKind.VAR:
            head = self._advance()
            if self._peek().kind == TokenKind.LPAREN:
                raise ParseError(
                    f"语法错误（位置 {tok.pos}）：变量 ?{head.value} 不能作为函数名"
                )
            return Term(0, head.value, is_var=True)
        head = self._advance()
        if self._peek().kind != TokenKind.LPAREN:
            return Term(0, head.value)
        self._advance()  # consume (
        args: list[Term] = []
        if self._peek().kind == TokenKind.RPAREN:
            raise ParseError("语法错误：函数调用至少需要一个参数")
        args.append(self.parse_expr())
        if self._peek().kind == TokenKind.COMMA:
            self._advance()
            args.append(self.parse_expr())
        if self._peek().kind != TokenKind.RPAREN:
            bad = self._peek()
            raise ParseError(
                f"语法错误（位置 {bad.pos}）：函数只允许一元或二元，"
                f"多余的 {bad.value!r}"
            )
        self._advance()  # consume )
        if len(args) not in (1, 2):
            raise ParseError("语法错误：函数只允许一元或二元")
        return Term(len(args), head.value, tuple(args))


def parse(text: str) -> Term:
    """解析单个表达式；空串或多余内容均视为语法错误。"""
    if not isinstance(text, str) or not text.strip():
        raise ParseError("语法错误：表达式为空")
    try:
        parser = _Parser(tokenize(text))
        term = parser.parse_expr()
        rest = parser._peek()
        if rest.kind != TokenKind.EOF:
            raise ParseError(
                f"语法错误（位置 {rest.pos}）：表达式后存在多余内容 {rest.value!r}"
            )
    except LexerError as exc:
        raise ParseError(str(exc)) from exc
    return term


def node_count(term: Term) -> int:
    """统计 AST 节点数（叶子与复合节点都计入声明的 80 节点上限）。"""
    return 1 + sum(node_count(a) for a in term.args)


def iter_vars(term: Term) -> set[str]:
    """收集规则变量名（不含 ? 前缀）。"""
    if term.kind == 0:
        return {term.name} if term.is_var else set()
    out: set[str] = set()
    for arg in term.args:
        out |= iter_vars(arg)
    return out


def has_variables(term: Term) -> bool:
    if term.kind == 0:
        return term.is_var
    return any(has_variables(a) for a in term.args)
