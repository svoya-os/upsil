# SPDX-License-Identifier: Apache-2.0
"""UpsiL lexer: source text -> tokens with positions.

Newlines end statements. The lexer emits a NEWLINE token for a line break
unless the statement obviously continues:

* inside ( ) and [ ] -- the innermost open bracket decides; braces are used
  both for blocks and for dict literals, so inside { } the parser decides;
* after a token that cannot end an expression: a binary operator, ',', ':',
  '=', '.', '=>', '->', 'and', 'or', 'not', 'in';
* before a line that starts with '.' (method chains).

Strings are lexed together with their ``{...}`` interpolations: the embedded
expression is tokenised here and parsed later by the parser, never evaluated
as text.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

from .errors import CompileError, Diagnostic
from .keywords import HARD_KEYWORDS, OPERATORS
from .nodes import Span

KEYWORDS = frozenset(HARD_KEYWORDS)

CONTINUATION_OPS = frozenset({
    "..=", "..", "**", "=>", "->", "==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "%=",
    "+", "-", "*", "/", "%", "@", "<", ">", "=", ",", ":", ".",
})
CONTINUATION_KWS = frozenset({"and", "or", "not", "in"})

_PAIRS = {"(": ")", "[": "]", "{": "}"}

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", '"': '"', "'": "'",
            "\\": "\\", "{": "{", "}": "}"}

_NUMBER_RE = re.compile(r"""
      0[xX][0-9a-fA-F](?:_?[0-9a-fA-F])*
    | 0[bB][01](?:_?[01])*
    | 0[oO][0-7](?:_?[0-7])*
    | [0-9](?:_?[0-9])*(?:\.[0-9](?:_?[0-9])*)?(?:[eE][+-]?[0-9](?:_?[0-9])*)?
""", re.VERBOSE)

_HEX = "0123456789abcdefABCDEF"


@dataclass
class InterpToken:
    """The tokens of one ``{...}`` inside a string literal."""
    tokens: List["Token"]
    spec: Optional[str]
    span: Span


@dataclass
class Token:
    kind: str          # NAME KW INT FLOAT STRING OP NEWLINE EOF
    value: object      # STRING: list of str | InterpToken
    span: Span
    text: str = ""

    def unexpected(self) -> Tuple[str, str]:
        """``(en, ru)`` phrases "unexpected ..." describing this token."""
        k, v = self.kind, self.value
        if k == "NEWLINE":
            return "unexpected end of line", "неожиданный конец строки"
        if k == "EOF":
            return "unexpected end of file", "неожиданный конец файла"
        if k == "NAME":
            return f"unexpected name '{v}'", f"неожиданное имя '{v}'"
        if k in ("INT", "FLOAT"):
            return f"unexpected number {self.text}", f"неожиданное число {self.text}"
        if k == "STRING":
            return "unexpected string", "неожиданная строка"
        return f"unexpected '{v}'", f"неожиданный токен '{v}'"


class _InterpMode:
    def __init__(self, multiline: bool, string_span: Span):
        self.multiline = multiline
        self.string_span = string_span


class Lexer:
    def __init__(self, source: str, filename: str = "<input>"):
        self.src = normalize_source(source)
        self.filename = filename
        self.n = len(self.src)
        self.pos = 0
        self.line = 1
        self.col = 1

    # ------------------------------------------------------------------ helpers
    def peek(self, k: int = 0) -> str:
        i = self.pos + k
        return self.src[i] if i < self.n else ""

    def advance(self, count: int = 1) -> None:
        for _ in range(count):
            if self.pos >= self.n:
                return
            ch = self.src[self.pos]
            self.pos += 1
            if ch == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1

    def fail(self, span: Span, en: str, ru: str, incomplete: bool = False) -> None:
        raise CompileError([Diagnostic(span, en, ru, incomplete=incomplete)], self.filename, self.src)

    def here(self, width: int = 1) -> Span:
        return Span(self.line, self.col, self.line, self.col + width)

    # ------------------------------------------------------------------ main loop
    def tokenize(self) -> List[Token]:
        tokens, _spec = self._run(None)
        return tokens

    def _run(self, interp: Optional[_InterpMode]) -> Tuple[List[Token], Optional[str]]:
        toks: List[Token] = []
        brackets: List[Tuple[str, Span]] = []
        pending_nl: Optional[Span] = None
        spec: Optional[str] = None

        def add(tok: Token) -> None:
            nonlocal pending_nl
            if pending_nl is not None:
                if (interp is None and toks and toks[-1].kind != "NEWLINE"
                        and _newline_ends_statement(toks[-1], brackets, tok)):
                    toks.append(Token("NEWLINE", "\n", pending_nl, "\n"))
                pending_nl = None
            toks.append(tok)

        def newline_seen(span: Span) -> None:
            nonlocal pending_nl
            if interp is not None and not interp.multiline:
                self.fail(interp.string_span,
                          "unterminated string: a line break inside \"...\" (use \\n or \"\"\"...\"\"\")",
                          "незакрытая строка: перевод строки внутри \"...\" (используйте \\n или \"\"\"...\"\"\")")
            if pending_nl is None:
                pending_nl = span

        while True:
            ch = self.peek()
            if ch == "":
                if interp is not None:
                    self.fail(interp.string_span, "unterminated string", "незакрытая строка",
                              incomplete=interp.multiline)
                break
            if ch == "\n":
                newline_seen(self.here())
                self.advance()
                continue
            if ch in " \t\r\f\v":
                self.advance()
                continue
            if ch == "/" and self.peek(1) == "/":
                while self.peek() not in ("\n", ""):
                    self.advance()
                continue
            if ch == "/" and self.peek(1) == "*":
                nl = self._block_comment()
                if nl is not None:
                    newline_seen(nl)
                continue
            if interp is not None and not brackets:
                if ch == "}":
                    break
                if ch == ":":
                    spec = self._format_spec(interp)
                    break
            if ch in "0123456789":
                add(self._number())
                continue
            if ch == '"':
                add(self._string())
                continue
            if ch == "_" or ch.isalpha():
                add(self._name())
                continue
            op = self._operator()
            span = self.here(len(op))
            tok = Token("OP", op, span, op)
            if op in (")", "]", "}"):
                if not brackets:
                    self.fail(span, f"unmatched '{op}'", f"лишняя закрывающая скобка '{op}'")
                opened, opened_at = brackets[-1]
                if _PAIRS[opened] != op:
                    self.fail(span,
                              f"'{op}' does not match '{opened}' opened at {opened_at.line}:{opened_at.col}",
                              f"'{op}' не соответствует '{opened}', открытой в {opened_at.line}:{opened_at.col}")
            self.advance(len(op))
            add(tok)   # decides about a pending line break before the bracket stack changes
            if op in _PAIRS:
                brackets.append((op, span))
            elif op in (")", "]", "}"):
                brackets.pop()

        if interp is None:
            if brackets:
                opened, opened_at = brackets[-1]
                self.fail(opened_at, f"'{opened}' is never closed", f"скобка '{opened}' не закрыта",
                          incomplete=True)
            last = toks[-1] if toks else None
            if last is not None and last.kind != "NEWLINE" and not _is_continuation(last):
                toks.append(Token("NEWLINE", "\n", self.here(), ""))
        toks.append(Token("EOF", None, self.here(), ""))
        return toks, spec

    # ------------------------------------------------------------------ pieces
    def _block_comment(self) -> Optional[Span]:
        start = self.here(2)
        first_nl: Optional[Span] = None
        self.advance(2)
        depth = 1
        while depth:
            ch = self.peek()
            if ch == "":
                self.fail(start, "unterminated comment /* ... */", "незакрытый комментарий /* ... */",
                          incomplete=True)
            if ch == "/" and self.peek(1) == "*":
                depth += 1
                self.advance(2)
            elif ch == "*" and self.peek(1) == "/":
                depth -= 1
                self.advance(2)
            else:
                if ch == "\n" and first_nl is None:
                    first_nl = self.here()
                self.advance()
        return first_nl

    def _operator(self) -> str:
        src, pos = self.src, self.pos
        ch = src[pos]
        if src.startswith("&&", pos):
            self.fail(self.here(2), "use 'and' instead of '&&'", "используйте 'and' вместо '&&'")
        if src.startswith("||", pos):
            self.fail(self.here(2), "use 'or' instead of '||'", "используйте 'or' вместо '||'")
        if ch == "!" and not src.startswith("!=", pos):
            self.fail(self.here(), "use 'not' instead of '!'", "используйте 'not' вместо '!'")
        for op in OPERATORS:
            if src.startswith(op, pos):
                return op
        if ch == "'":
            self.fail(self.here(), "strings are written in double quotes: \"...\"",
                      "строки пишутся в двойных кавычках: \"...\"")
        if ch == "#":
            self.fail(self.here(), "comments start with //", "комментарии начинаются с //")
        shown = ch if ch.isprintable() else f"U+{ord(ch):04X}"
        self.fail(self.here(), f"unexpected character '{shown}'", f"неожиданный символ '{shown}'")
        raise AssertionError("unreachable")

    def _name(self) -> Token:
        sl, sc, sp = self.line, self.col, self.pos
        while True:
            ch = self.peek()
            if ch and (ch == "_" or ch.isalnum() or unicodedata.category(ch) in ("Mn", "Mc", "Pc")):
                self.advance()
            else:
                break
        raw = self.src[sp:self.pos]
        word = unicodedata.normalize("NFKC", raw)
        span = Span(sl, sc, self.line, self.col)
        if not word.isidentifier():
            self.fail(span, f"invalid name '{raw}'", f"недопустимое имя '{raw}'")
        return Token("KW" if word in KEYWORDS else "NAME", word, span, raw)

    def _number(self) -> Token:
        sl, sc, sp = self.line, self.col, self.pos
        m = _NUMBER_RE.match(self.src, self.pos)
        assert m is not None
        text = m.group(0)
        self.advance(len(text))
        nxt = self.peek()
        if nxt and (nxt == "_" or nxt.isalnum()):
            while self.peek() and (self.peek() == "_" or self.peek().isalnum()):
                self.advance()
            bad = self.src[sp:self.pos]
            self.fail(Span(sl, sc, self.line, self.col), f"invalid number '{bad}'",
                      f"неверная запись числа '{bad}'")
        span = Span(sl, sc, self.line, self.col)
        clean = text.replace("_", "")
        if clean[:2].lower() in ("0x", "0b", "0o"):
            return Token("INT", int(clean, 0), span, text)
        if any(c in clean for c in ".eE"):
            return Token("FLOAT", float(clean), span, text)
        return Token("INT", int(clean), span, text)

    def _format_spec(self, interp: _InterpMode) -> Optional[str]:
        self.advance()  # ':'
        start = self.pos
        while self.peek() not in ("}", ""):
            ch = self.peek()
            if ch == "\n" and not interp.multiline:
                break
            if ch == "{":
                self.fail(self.here(), "nested { } in a format spec are not supported",
                          "вложенные { } в формате не поддерживаются")
            self.advance()
        if self.peek() != "}":
            self.fail(interp.string_span, "unterminated string", "незакрытая строка",
                      incomplete=interp.multiline and self.peek() == "")
        spec = self.src[start:self.pos]
        return spec or None

    def _escape(self) -> str:
        span = self.here(2)
        nxt = self.peek(1)
        if nxt in _ESCAPES:
            self.advance(2)
            return _ESCAPES[nxt]
        if nxt == "u":
            if self.peek(2) == "{":
                j = 3
                while self.peek(j) in _HEX and self.peek(j):
                    j += 1
                digits = self.src[self.pos + 3:self.pos + j]
                if self.peek(j) != "}" or not 1 <= len(digits) <= 6:
                    self.fail(self.here(j + 1), "bad escape: expected \\u{hex}", "неверная escape-последовательность: ожидалось \\u{hex}")
                width = j + 1
            else:
                digits = self.src[self.pos + 2:self.pos + 6]
                if len(digits) != 4 or any(c not in _HEX for c in digits):
                    self.fail(self.here(2 + len(digits)), "bad escape: expected \\uXXXX (4 hex digits)",
                              "неверная escape-последовательность: ожидалось \\uXXXX (4 шестнадцатеричные цифры)")
                width = 6
            code = int(digits, 16)
            if code > 0x10FFFF or 0xD800 <= code <= 0xDFFF:
                self.fail(self.here(width), f"no such character: \\u{digits}", f"нет такого символа: \\u{digits}")
            self.advance(width)
            return chr(code)
        shown = nxt if nxt and nxt != "\n" else ""
        self.fail(span, f"unknown escape '\\{shown}' (to write a backslash use \\\\)",
                  f"неизвестная escape-последовательность '\\{shown}' (обратная косая черта пишется как \\\\)")
        raise AssertionError("unreachable")

    def _string(self) -> Token:
        sl, sc, sp = self.line, self.col, self.pos
        triple = self.src.startswith('"""', self.pos)
        string_span = Span(sl, sc, sl, sc + (3 if triple else 1))
        self.advance(3 if triple else 1)
        # one entry per physical line: [raw indentation, parts]
        lines: List[List] = [["", []]]
        buf: List[str] = []

        def flush() -> None:
            if buf:
                lines[-1][1].append("".join(buf))
                buf.clear()

        while True:
            ch = self.peek()
            if ch == "":
                self.fail(string_span, "unterminated string", "незакрытая строка", incomplete=triple)
            if triple:
                if self.src.startswith('"""', self.pos):
                    self.advance(3)
                    break
            elif ch == '"':
                self.advance()
                break
            if ch == "\n":
                if not triple:
                    self.fail(string_span,
                              "unterminated string: a line break inside \"...\" (use \\n or \"\"\"...\"\"\")",
                              "незакрытая строка: перевод строки внутри \"...\" (используйте \\n или \"\"\"...\"\"\")")
                flush()
                self.advance()
                start = self.pos
                while self.peek() in (" ", "\t") and self.peek():
                    self.advance()
                lines.append([self.src[start:self.pos], []])
                continue
            if ch == "\\":
                buf.append(self._escape())
                continue
            if ch == "{":
                flush()
                open_line, open_col = self.line, self.col
                self.advance()
                sub, spec = self._run(_InterpMode(triple, string_span))
                if self.peek() != "}":
                    self.fail(Span.point(open_line, open_col), "'{' in a string is never closed",
                              "'{' в строке не закрыта")
                self.advance()
                span = Span(open_line, open_col, self.line, self.col)
                if len(sub) == 1:
                    self.fail(span, "empty { } in a string (to write a brace use \\{)",
                              "пустые { } в строке (чтобы написать скобку, используйте \\{)")
                lines[-1][1].append(InterpToken(sub, spec, span))
                continue
            buf.append(ch)
            self.advance()
        flush()
        parts = _finish_string(lines, triple)
        return Token("STRING", parts, Span(sl, sc, self.line, self.col), self.src[sp:self.pos])


# ---------------------------------------------------------------------- helpers

def normalize_source(source: str) -> str:
    if source.startswith("﻿"):
        source = source[1:]
    return source.replace("\r\n", "\n").replace("\r", "\n")


def _is_continuation(tok: Token) -> bool:
    return ((tok.kind == "OP" and tok.value in CONTINUATION_OPS)
            or (tok.kind == "KW" and tok.value in CONTINUATION_KWS))


def _newline_ends_statement(prev: Token, brackets: List[Tuple[str, Span]], nxt: Token) -> bool:
    if brackets and brackets[-1][0] in "([":
        return False
    if _is_continuation(prev):
        return False
    if nxt.kind == "OP" and nxt.value == ".":
        return False
    return True


def _is_blank(parts: list) -> bool:
    return all(isinstance(p, str) for p in parts) and "".join(parts).strip(" \t") == ""


def _merge(parts: list) -> List[Union[str, InterpToken]]:
    out: List[Union[str, InterpToken]] = []
    for p in parts:
        if isinstance(p, str):
            if not p:
                continue
            if out and isinstance(out[-1], str):
                out[-1] = out[-1] + p
                continue
        out.append(p)
    return out


def _finish_string(lines: List[List], triple: bool) -> List[Union[str, InterpToken]]:
    """Join physical lines; strip common indentation of a multi-line string.

    A triple-quoted string whose opening quotes end the line is dedented, like
    in Swift or Java: the first line break is dropped, the line that holds the
    closing quotes is dropped if it is blank, and the indentation common to the
    remaining non-blank lines (and to the closing quotes) is removed.
    """
    if not triple:
        return _merge(lines[0][1])
    if len(lines) > 1 and _is_blank(lines[0][1]):
        body = lines[1:]
        closing: Optional[str] = None
        if body and not body[-1][1]:
            closing = body[-1][0]
            body = body[:-1]
        indents = [ind for ind, parts in body if parts and not _is_blank(parts)]
        if closing is not None:
            indents.append(closing)
        common = os.path.commonprefix(indents) if indents else ""
        out: list = []
        for i, (ind, parts) in enumerate(body):
            if i:
                out.append("\n")
            if parts and not _is_blank(parts):
                out.append(ind[len(common):])
                out.extend(parts)
        return _merge(out)
    out = []
    for i, (ind, parts) in enumerate(lines):
        if i:
            out.append("\n")
        out.append(ind)
        out.extend(parts)
    return _merge(out)


def tokenize(source: str, filename: str = "<input>") -> List[Token]:
    return Lexer(source, filename).tokenize()
