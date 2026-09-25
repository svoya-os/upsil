# SPDX-License-Identifier: Apache-2.0
"""Shared helpers for the UpsiL test suite (standard library only)."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Dict, Iterator, List, Optional

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from upsil.errors import CompileError  # noqa: E402


@contextlib.contextmanager
def env(**values: Optional[str]) -> Iterator[None]:
    """Temporarily set (or with None, remove) environment variables."""
    saved = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def lang(code: str):
    return env(UPSIL_LANG=code)


def run_upl(source: str, filename: str = "test.upl", stdin: Optional[str] = None) -> str:
    """Compile and run UpsiL source in this process; return what it printed."""
    from upsil.compiler import compile_source
    program = compile_source(source, filename)
    out = io.StringIO()
    saved_stdin = sys.stdin
    try:
        if stdin is not None:
            sys.stdin = io.StringIO(stdin)
        with contextlib.redirect_stdout(out):
            exec(program.code, {"__name__": "__main__"})
    finally:
        sys.stdin = saved_stdin
    return out.getvalue()


def compile_error(source: str, *, lint: bool = False, filename: str = "t.upl") -> CompileError:
    """The CompileError that compiling ``source`` raises (fails the test if none)."""
    from upsil.compiler import check_source, compile_source
    try:
        if lint:
            check_source(source, filename, lint_types=True)
        else:
            compile_source(source, filename)
    except CompileError as exc:
        return exc
    raise AssertionError(f"no compile error for:\n{source}")


def clean_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """An environment for subprocesses: no user config, no real model server, English."""
    e = {k: v for k, v in os.environ.items()
         if not k.startswith("UPSIL_") and k not in ("OPENAI_API_KEY", "LANG", "LC_ALL", "LC_MESSAGES", "LANGUAGE")}
    e["PYTHONPATH"] = str(ROOT) + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    e["UPSIL_CONFIG"] = os.devnull
    e["UPSIL_LLM_URL"] = "http://127.0.0.1:9/v1"   # discard port: nothing answers
    e["PYTHONIOENCODING"] = "utf-8"
    e["LANG"] = "C.UTF-8"
    if extra:
        e.update(extra)
    return e


def run_cli(args: List[str], *, extra_env: Optional[Dict[str, str]] = None, stdin: Optional[str] = None,
            cwd: Optional[str] = None, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "upsil", *args], capture_output=True, text=True,
                          encoding="utf-8", env=clean_env(extra_env), input=stdin, cwd=cwd or str(ROOT),
                          timeout=timeout)


class UpsilTestCase(unittest.TestCase):
    def assertCompileError(self, source: str, fragment: str, line: Optional[int] = None,
                           col: Optional[int] = None, *, lint: bool = False) -> CompileError:
        with lang("en"):
            exc = compile_error(source, lint=lint)
            messages = [d.message for d in exc.diagnostics]
        self.assertTrue(any(fragment in m for m in messages),
                        f"{fragment!r} not in {messages!r}")
        d = next(d for d in exc.diagnostics if fragment in d.en)
        if line is not None:
            self.assertEqual(d.span.line, line, exc.format())
        if col is not None:
            self.assertEqual(d.span.col, col, exc.format())
        return exc

    def assertRuns(self, source: str, expected: str, stdin: Optional[str] = None) -> None:
        self.assertEqual(run_upl(source, stdin=stdin), expected)
