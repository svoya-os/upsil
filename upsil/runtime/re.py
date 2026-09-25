# SPDX-License-Identifier: Apache-2.0
r"""re: regular expressions. Write patterns as raw strings, where \ and { } are plain characters:

    import re
    re.test(r"\d{4}", "в 2026 году")                        // true
    re.find(r"\d+", "цена 450 руб")                         // "450"
    re.find_all(r"#(\w+)", "#ии #сос")                      // ["ии", "сос"]
    re.groups(r"(\w+)@(\w+)", "max@sos")                    // ["max", "sos"]
    re.replace(r"\s+", " ", "много    пробелов")            // "много пробелов"
    re.replace(r"\d+", m => str(int(m) * 2), "3 и 4")       // "6 и 8"
    re.split(r"[,;]\s*", "a, b;c")                           // ["a", "b", "c"]

Every function takes ``ignore_case = true``. Python's full ``re`` is ``import py "re"``.
"""

from __future__ import annotations

import re as _re
from typing import Any, Callable, List, Optional, Union

from ..errors import UpsilError

__all__ = ["test", "find", "find_all", "groups", "replace", "split", "escape"]


def _compile(pattern: str, ignore_case: bool) -> "_re.Pattern[str]":
    try:
        return _re.compile(pattern, _re.IGNORECASE if ignore_case else 0)
    except _re.error as exc:
        raise UpsilError(f"bad regular expression {pattern!r}: {exc}",
                         f"неверное регулярное выражение {pattern!r}: {exc}") from None


def test(pattern: str, text: str, ignore_case: bool = False) -> bool:
    """Does the pattern occur anywhere in the text?"""
    return _compile(pattern, ignore_case).search(text) is not None


def find(pattern: str, text: str, ignore_case: bool = False) -> Optional[str]:
    """The first match, or null."""
    m = _compile(pattern, ignore_case).search(text)
    return m.group(0) if m else None


def find_all(pattern: str, text: str, ignore_case: bool = False) -> List[Any]:
    """Every match; with one group in the pattern — that group, with several — a list of them."""
    out: List[Any] = []
    for m in _compile(pattern, ignore_case).finditer(text):
        if m.re.groups == 0:
            out.append(m.group(0))
        elif m.re.groups == 1:
            out.append(m.group(1))
        else:
            out.append(list(m.groups()))
    return out


def groups(pattern: str, text: str, ignore_case: bool = False) -> Optional[List[Optional[str]]]:
    """The groups ( ) of the first match as a list, or null when nothing matches."""
    m = _compile(pattern, ignore_case).search(text)
    return list(m.groups()) if m else None


def replace(pattern: str, replacement: Union[str, Callable[[str], Any]], text: str,
            ignore_case: bool = False, count: int = 0) -> str:
    r"""Replace matches: ``replacement`` is text (\1 refers to a group) or a function of the matched text."""
    rx = _compile(pattern, ignore_case)
    if callable(replacement):
        from .prelude import show
        return rx.sub(lambda m: show(replacement(m.group(0))), text, count=count)
    return rx.sub(replacement, text, count=count)


def split(pattern: str, text: str, ignore_case: bool = False) -> List[str]:
    """The pieces of the text between matches."""
    return _compile(pattern, ignore_case).split(text)


def escape(text: str) -> str:
    """The text as a pattern that matches it literally."""
    return _re.escape(text)
