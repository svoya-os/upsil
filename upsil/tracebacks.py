# SPDX-License-Identifier: Apache-2.0
"""Run-time errors shown with UpsiL source lines instead of Python internals.

    Ошибка выполнения (последний вызов — внизу):
      examples/fail.upl:6, в <программа>
        main()
      examples/fail.upl:3, в main
        print(1 / x)
              ^^^^^
    ZeroDivisionError: division by zero — деление на ноль

Only frames of compiled UpsiL files are shown. ``UPSIL_TRACEBACK=python``
prints the full Python traceback instead (for debugging UpsiL itself).
"""

from __future__ import annotations

import linecache
import os
import traceback
from typing import List, Optional, Set

from .errors import UpsilError
from .i18n import plural_ru, tr

# file names of compiled UpsiL code (filled by upsil.compiler.register_source)
UPSIL_FILES: Set[str] = set()

_HINTS_RU = {
    "ZeroDivisionError": "деление на ноль",
    "IndexError": "индекс за пределами списка или строки",
    "KeyError": "в словаре нет такого ключа",
    "TypeError": "значение не того типа",
    "ValueError": "неподходящее значение",
    "AttributeError": "у значения нет такого поля или метода",
    "NameError": "имя ещё не определено в момент выполнения",
    "UnboundLocalError": "переменная ещё не получила значение",
    "RecursionError": "слишком глубокая рекурсия",
    "FileNotFoundError": "файл не найден",
    "IsADirectoryError": "это папка, а не файл",
    "PermissionError": "нет прав доступа",
    "UnicodeDecodeError": "файл не в кодировке UTF-8",
    "OverflowError": "слишком большое число",
    "ModuleNotFoundError": "модуль Python не установлен",
}


def _char_col(line: str, byte_col: Optional[int]) -> Optional[int]:
    if byte_col is None:
        return None
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", "replace"))


def _frame_lines(frame: traceback.FrameSummary) -> List[str]:
    name = frame.name
    if name == "<module>":
        name = tr("<program>", "<программа>")
    out = [f"  {frame.filename}:{frame.lineno}, {tr('in', 'в')} {name}"]
    line = linecache.getline(frame.filename, frame.lineno or 0).rstrip("\n")
    if not line.strip():
        return out
    stripped = line.lstrip()
    indent = len(line) - len(stripped)
    out.append(f"    {stripped.rstrip()}")
    colno = getattr(frame, "colno", None)
    end_colno = getattr(frame, "end_colno", None)
    end_lineno = getattr(frame, "end_lineno", None)
    start = _char_col(line, colno)
    end = _char_col(line, end_colno)
    if start is None or end is None or end_lineno != frame.lineno or end <= start:
        return out
    start, end = max(start - indent, 0), end - indent
    if start == 0 and end >= len(stripped.rstrip()):
        return out                      # the whole line: carets add nothing
    out.append("    " + " " * start + "^" * (end - start))
    return out


def error_line(exc: BaseException) -> str:
    if isinstance(exc, UpsilError):
        return f"{tr('error', 'ошибка')}: {exc}"
    name = type(exc).__name__
    text = str(exc)
    line = f"{name}: {text}" if text else name
    hint = _HINTS_RU.get(name)
    if hint and tr("en", "ru") == "ru":
        line += f" — {hint}"
    return line


def format_runtime_error(exc: BaseException) -> str:
    if os.environ.get("UPSIL_TRACEBACK", "").lower() == "python":
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip("\n")
    frames = traceback.extract_tb(exc.__traceback__)
    shown = [f for f in frames if f.filename in UPSIL_FILES]
    lines = []
    if shown:
        lines.append(tr("Runtime error (most recent call last):", "Ошибка выполнения (последний вызов — внизу):"))
        previous = None
        repeats = 0
        for frame in shown + [None]:
            key = None if frame is None else (frame.filename, frame.lineno, frame.name)
            if key is not None and key == previous:
                repeats += 1
                if repeats < 3:
                    lines.extend(_frame_lines(frame))
                continue
            if repeats >= 3:   # deep recursion: say how often the same call repeated
                n = repeats - 2
                lines.append("  " + tr(f"[the same call repeated {n} more time{'' if n == 1 else 's'}]",
                                       f"[тот же вызов повторяется ещё {n} {plural_ru(n, 'раз', 'раза', 'раз')}]"))
            if frame is None:
                break
            previous, repeats = key, 0
            lines.extend(_frame_lines(frame))
    lines.append(error_line(exc))
    return "\n".join(lines)
