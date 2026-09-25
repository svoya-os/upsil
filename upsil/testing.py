# SPDX-License-Identifier: Apache-2.0
"""``upsil test``: run the tests of an UpsiL project.

A test file is ``test_*.upl`` or ``*_test.upl``; a test is a top-level ``fun test_...()`` in it.
The file's top level runs first (declarations, imports), then each test in the order of the
file. A test passes when it returns; ``assert`` that fails, or any error, fails it::

    tests/test_text.upl
      ✓ test_words
      ✗ test_upper — проверка не прошла: upper("ай") == "АЙ!"  (tests/test_text.upl:7)
    2 теста: 1 прошёл, 1 не прошёл (0,01 с)
"""

from __future__ import annotations

import builtins
import os
import sys
import time
import traceback
from typing import List, Tuple

from .errors import AssertFailed, CompileError, UpsilError
from .i18n import plural_ru, tr


def discover(paths: List[str]) -> List[str]:
    """Test files in the given files and folders (recursively; hidden folders are skipped)."""
    found: List[str] = []
    for path in paths or ["."]:
        if os.path.isfile(path):
            found.append(path)
            continue
        for root, dirs, files in os.walk(path):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "node_modules"))
            for name in sorted(files):
                if name.endswith(".upl") and (name.startswith("test_") or name.endswith("_test.upl")):
                    found.append(os.path.normpath(os.path.join(root, name)))
    return found


def _where(exc: BaseException, filename: str) -> str:
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == filename]
    return f"{frames[-1].filename}:{frames[-1].lineno}" if frames else ""


def _describe(exc: BaseException) -> str:
    if isinstance(exc, (UpsilError, AssertFailed)):
        return str(exc)
    from .tracebacks import error_line
    return error_line(exc)


def run_file(path: str, out) -> Tuple[int, int, bool]:
    """Run one test file: (passed, failed, compiled)."""
    from .compiler import compile_source
    try:
        with open(path, encoding="utf-8") as f:
            source = f.read()
    except OSError as exc:
        out.write(f"{path}: {exc.strerror or exc}\n")
        return 0, 1, False
    out.write(f"{path}\n")
    try:
        program = compile_source(source, path)
    except CompileError as exc:
        out.write(exc.format() + "\n")
        return 0, 1, False
    namespace = {"__name__": "__test__", "__file__": os.path.abspath(path), "__builtins__": builtins}
    sys.path.insert(0, os.path.dirname(os.path.abspath(path)))
    try:
        exec(program.code, namespace)
    except Exception as exc:  # noqa: BLE001 - the file's top level failed: every test in it counts as failed
        out.write(f"  ✗ {tr('top level', 'верхний уровень')} — {_describe(exc)}  ({_where(exc, path)})\n")
        return 0, 1, True
    finally:
        sys.path.pop(0)
    tests = [(name, fn) for name, fn in namespace.items()
             if name.startswith("test_") and callable(fn) and getattr(getattr(fn, "__code__", None), "co_filename", None) == path]
    tests.sort(key=lambda item: item[1].__code__.co_firstlineno)
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - a failing test is reported, the others still run
            failed += 1
            where = _where(exc, path)
            out.write(f"  ✗ {name} — {_describe(exc)}{f'  ({where})' if where else ''}\n")
        else:
            passed += 1
            out.write(f"  ✓ {name}\n")
    if not tests:
        out.write("  " + tr("(no fun test_...() here)", "(здесь нет fun test_...())") + "\n")
    return passed, failed, True


def main(paths: List[str]) -> int:
    files = discover(paths)
    out = sys.stdout
    if not files:
        out.write(tr("no test files (test_*.upl or *_test.upl)", "нет файлов с тестами (test_*.upl или *_test.upl)") + "\n")
        return 64
    started = time.monotonic()
    passed = failed = 0
    compile_errors = False
    for path in files:
        p, f, compiled = run_file(path, out)
        passed += p
        failed += f
        compile_errors = compile_errors or not compiled
    total = passed + failed
    seconds = time.monotonic() - started
    summary_en = f"{total} test{'' if total == 1 else 's'}: {passed} passed, {failed} failed ({seconds:.2f} s)"
    def went(n: int) -> str:
        return "прошёл" if n % 10 == 1 and n % 100 != 11 else "прошли"
    summary_ru = (f"{total} {plural_ru(total, 'тест', 'теста', 'тестов')}: {passed} {went(passed)}, "
                  f"{failed} не {went(failed)} ({seconds:.2f} с)")
    out.write(tr(summary_en, summary_ru) + "\n")
    if compile_errors:
        return 2
    return 0 if failed == 0 else 1
