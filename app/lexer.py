"""词法分析：把受限表达式切分为 token。

表达式仅含：
  * 具名常量（裸标识符，如 ALT_LIMIT、a）
  * 规则变量（以 ? 开头的标识符，如 ?x）——只允许出现在规则中
  * 一元或二元函数调用 f(x) / f(x, y)
  * 圆括号与逗号
不允许内建运算符、数字字面量或字符串。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Token", "TokenKind", "tokenize", "LexerError"]


class TokenKind:
    IDENT = "IDENT"
    VAR = "VAR"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    COMMA = "COMMA"
    EOF = "EOF"


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    pos: int


class LexerError(ValueError):
    def __init__(self, message: str, pos: int):
        super().__init__(f"语法错误（位置 {pos}）：{message}")
        self.pos = pos


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "?":
            start = i
            i += 1
            if i >= n or not (text[i].isalpha() or text[i] == "_"):
                raise LexerError("变量名 '?' 后必须紧跟字母或下划线", start)
            vstart = i
            i += 1
            while i < n and (text[i].isalnum() or text[i] == "_"):
                i += 1
            tokens.append(Token(TokenKind.VAR, text[vstart:i], start))
            continue
        if ch.isalpha() or ch == "_":
            start = i
            i += 1
            while i < n and (text[i].isalnum() or text[i] == "_"):
                i += 1
            tokens.append(Token(TokenKind.IDENT, text[start:i], start))
            continue
        if ch == "(":
            tokens.append(Token(TokenKind.LPAREN, ch, i))
            i += 1
            continue
        if ch == ")":
            tokens.append(Token(TokenKind.RPAREN, ch, i))
            i += 1
            continue
        if ch == ",":
            tokens.append(Token(TokenKind.COMMA, ch, i))
            i += 1
            continue
        raise LexerError(f"非法字符 {ch!r}", i)
    tokens.append(Token(TokenKind.EOF, "", n))
    return tokens
