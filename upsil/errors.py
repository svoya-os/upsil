# SPDX-License-Identifier: Apache-2.0
"""Errors: compile-time diagnostics with positions, and run-time UpsilError.

A compile error looks like this (Russian when LANG starts with "ru")::

    hello.upl:12:5: ошибка: неожиданный токен ')' — ожидалось выражение
       12 | print(1 + )
          |           ^
"""

from __future__ import annotations

from typing import List, Optional

from .i18n import tr
from .nodes import Span


class UpsilError(Exception):
    """An error raised by the UpsiL runtime, with a Russian and an English text."""

    def __init__(self, en: str, ru: Optional[str] = None):
        super().__init__(en)
        self.en = en
        self.ru = ru if ru is not None else en

    def __str__(self) -> str:
        return tr(self.en, self.ru)


class Diagnostic:
    """One compile-time message attached to a source position."""

    def __init__(self, span: Span, en: str, ru: str, *, severity: str = "error",
                 incomplete: bool = False):
        self.span = span
        self.en = en
        self.ru = ru
        self.severity = severity
        # True when more input could fix it (unclosed bracket, end of file...);
        # the REPL uses this to ask for a continuation line.
        self.incomplete = incomplete

    @property
    def message(self) -> str:
        return tr(self.en, self.ru)

    def __repr__(self) -> str:
        return f"Diagnostic({self.span.line}:{self.span.col} {self.en!r})"


class CompileError(Exception):
    """One or more diagnostics that stop compilation."""

    def __init__(self, diagnostics: List[Diagnostic], filename: str, source: str):
        self.diagnostics = sorted(diagnostics, key=lambda d: (d.span.line, d.span.col))
        self.filename = filename
        self.source = source
        super().__init__(self.format())

    @property
    def incomplete(self) -> bool:
        return any(d.incomplete for d in self.diagnostics)

    def format(self) -> str:
        return "\n".join(format_diagnostic(d, self.filename, self.source)
                         for d in self.diagnostics)

    def __str__(self) -> str:
        return self.format()


def format_diagnostic(d: Diagnostic, filename: str, source: str) -> str:
    if d.severity == "warning":
        label = tr("warning", "предупреждение")
    else:
        label = tr("error", "ошибка")
    head = f"{filename}:{d.span.line}:{d.span.col}: {label}: {d.message}"
    lines = source.splitlines()
    if not 1 <= d.span.line <= len(lines):
        return head
    text = lines[d.span.line - 1].rstrip("\r\n")
    col = max(1, d.span.col)
    if d.span.end_line == d.span.line and d.span.end_col > col:
        width = d.span.end_col - col
    else:
        width = 1
    width = max(1, min(width, len(text) - col + 2))
    # keep tabs so the caret lines up in a terminal
    prefix = "".join("\t" if ch == "\t" else " " for ch in text[:col - 1])
    prefix += " " * max(0, col - 1 - len(text))
    number = str(d.span.line)
    gutter = " " * len(number)
    return (f"{head}\n"
            f"  {number} | {text}\n"
            f"  {gutter} | {prefix}{'^' * width}")
