# SPDX-License-Identifier: Apache-2.0
"""The ``upsil`` command (also ``python -m upsil``).

Exit codes: 0 success, 1 run-time error, 2 compile error, 64 usage error.
"""

from __future__ import annotations

import builtins
import os
import platform
import sys
from typing import List, Optional

from . import __version__
from .errors import CompileError
from .i18n import tr

EXIT_OK, EXIT_RUNTIME, EXIT_COMPILE, EXIT_USAGE = 0, 1, 2, 64

HELP_EN = f"""UpsiL {__version__}: a small language for AI scripts that compiles to readable Python.

Usage:
  upsil run FILE [ARGS...]    compile and run FILE; ARGS go to sys.args
  upsil FILE.upl [ARGS...]    the same
  upsil build FILE [-o OUT]   print the generated Python (or write it to OUT)
  upsil check FILE...         look for errors without running (also obvious type mismatches)
  upsil test [PATH...]        run the tests: fun test_...() in test_*.upl / *_test.upl files
  upsil repl                  interactive mode
  upsil version               print the version
  upsil help                  this help

Environment:
  UPSIL_LLM_URL     OpenAI-compatible API (default http://127.0.0.1:8080/v1; on SOS: sos models serve)
  UPSIL_LLM_MODEL   model name (default: [llm] model in ~/.config/upsil/config.toml, or the first one listed)
  UPSIL_LLM_KEY     API key for cloud endpoints (or OPENAI_API_KEY)
  UPSIL_LANG        ru or en (default: from LANG)
  UPSIL_TRACEBACK   "python" shows full Python tracebacks

Exit codes: 0 success, 1 run-time error, 2 compile error, 64 usage error.
Documentation: https://github.com/svoya-os/upsil
"""

HELP_RU = f"""UpsiL {__version__}: небольшой язык для ИИ-скриптов, компилируется в читаемый Python.

Использование:
  upsil run ФАЙЛ [АРГУМЕНТЫ...]   скомпилировать и запустить ФАЙЛ; АРГУМЕНТЫ попадут в sys.args
  upsil ФАЙЛ.upl [АРГУМЕНТЫ...]   то же самое
  upsil build ФАЙЛ [-o ВЫХОД]     показать получившийся Python (или записать в ВЫХОД)
  upsil check ФАЙЛ...             найти ошибки без запуска (и явные несовпадения типов)
  upsil test [ПУТЬ...]            запустить тесты: fun test_...() в файлах test_*.upl / *_test.upl
  upsil repl                      интерактивный режим
  upsil version                   версия
  upsil help                      эта справка

Переменные окружения:
  UPSIL_LLM_URL     API, совместимый с OpenAI (по умолчанию http://127.0.0.1:8080/v1; в СОС: sos models serve)
  UPSIL_LLM_MODEL   имя модели (по умолчанию [llm] model в ~/.config/upsil/config.toml или первая из списка)
  UPSIL_LLM_KEY     ключ API для облачных серверов (или OPENAI_API_KEY)
  UPSIL_LANG        ru или en (по умолчанию — по LANG)
  UPSIL_TRACEBACK   "python" — показывать полные трассировки Python

Коды выхода: 0 — успех, 1 — ошибка выполнения, 2 — ошибка компиляции, 64 — неверный вызов.
Документация: https://github.com/svoya-os/upsil
"""


def _help() -> str:
    return tr(HELP_EN, HELP_RU)


def _err(text: str) -> None:
    sys.stderr.write(text.rstrip("\n") + "\n")
    sys.stderr.flush()


def _usage(en: str, ru: str) -> int:
    _err(f"upsil: {tr(en, ru)}")
    _err(tr("See: upsil help", "Справка: upsil help"))
    return EXIT_USAGE


def _flush_stdout() -> None:
    try:
        sys.stdout.flush()
    except (OSError, ValueError):
        pass


def _setup_streams() -> None:
    """Never crash on a terminal that cannot show Cyrillic."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None and encoding != "utf8":
            try:
                reconfigure(errors="backslashreplace")
            except (ValueError, OSError):
                pass


class _SourceError(Exception):
    def __init__(self, code: int):
        self.code = code


def read_source(path: str) -> str:
    try:
        if path == "-":
            return sys.stdin.read()
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        _err(f"upsil: {tr('file not found', 'файл не найден')}: {path}")
        raise _SourceError(EXIT_USAGE) from None
    except IsADirectoryError:
        _err(f"upsil: {tr('this is a folder, not a file', 'это папка, а не файл')}: {path}")
        raise _SourceError(EXIT_USAGE) from None
    except UnicodeDecodeError:
        _err(f"upsil: {tr('the file is not UTF-8 text', 'файл не в кодировке UTF-8')}: {path}")
        raise _SourceError(EXIT_COMPILE) from None
    except OSError as exc:
        _err(f"upsil: {path}: {exc.strerror or exc}")
        raise _SourceError(EXIT_USAGE) from None


def execute(program, path: str, args: List[str]) -> int:
    """Run a compiled program like a script; returns the exit code."""
    from .tracebacks import format_runtime_error
    display = "<stdin>" if path == "-" else path
    sys.argv = [display] + list(args)
    if path != "-":
        sys.path.insert(0, os.path.dirname(os.path.abspath(path)))
    namespace = {"__name__": "__main__", "__file__": os.path.abspath(path) if path != "-" else display,
                 "__builtins__": builtins}
    try:
        exec(program.code, namespace)
    except SystemExit as exc:
        _flush_stdout()
        code = exc.code
        if code is None:
            return EXIT_OK
        if isinstance(code, int):
            return code
        _err(str(code))
        return EXIT_RUNTIME
    except KeyboardInterrupt:
        _flush_stdout()
        _err(tr("interrupted", "прервано"))
        return 130
    except BrokenPipeError:
        # the reader went away (`upsil run x.upl | head`): stop quietly
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except (OSError, ValueError, AttributeError):
            pass
        return EXIT_RUNTIME
    except BaseException as exc:  # noqa: B902 - every error of the user's program ends here
        _flush_stdout()
        _err(format_runtime_error(exc))
        return EXIT_RUNTIME
    _flush_stdout()
    return EXIT_OK


def cmd_run(rest: List[str]) -> int:
    from .compiler import compile_source
    if not rest or (rest[0].startswith("-") and rest[0] != "-"):
        return _usage("usage: upsil run FILE [ARGS...]", "использование: upsil run ФАЙЛ [АРГУМЕНТЫ...]")
    path, args = rest[0], rest[1:]
    try:
        source = read_source(path)
    except _SourceError as exc:
        return exc.code
    try:
        program = compile_source(source, "<stdin>" if path == "-" else path)
    except CompileError as exc:
        _err(exc.format())
        return EXIT_COMPILE
    return execute(program, path, args)


def cmd_build(rest: List[str]) -> int:
    from .compiler import compile_source
    out: Optional[str] = None
    files: List[str] = []
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg in ("-o", "--output"):
            if i + 1 >= len(rest):
                return _usage("-o needs a file name", "после -o нужно имя файла")
            out = rest[i + 1]
            i += 2
            continue
        if arg.startswith("--output="):
            out = arg.split("=", 1)[1]
        elif arg.startswith("-") and arg != "-":
            return _usage(f"unknown option {arg}", f"неизвестный параметр {arg}")
        else:
            files.append(arg)
        i += 1
    if len(files) != 1:
        return _usage("usage: upsil build FILE [-o OUT]", "использование: upsil build ФАЙЛ [-o ВЫХОД]")
    path = files[0]
    if out is not None and path != "-" and os.path.abspath(out) == os.path.abspath(path):
        return _usage("the output would overwrite the source file", "выходной файл совпадает с исходным")
    try:
        source = read_source(path)
    except _SourceError as exc:
        return exc.code
    try:
        program = compile_source(source, "<stdin>" if path == "-" else path)
    except CompileError as exc:
        _err(exc.format())
        return EXIT_COMPILE
    text = program.python_source()
    if out is None:
        sys.stdout.write(text)
        return EXIT_OK
    try:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as exc:
        _err(f"upsil: {out}: {exc.strerror or exc}")
        return EXIT_USAGE
    return EXIT_OK


def cmd_check(rest: List[str]) -> int:
    from .compiler import check_source
    if not rest or any(a.startswith("-") and a != "-" for a in rest):
        return _usage("usage: upsil check FILE...", "использование: upsil check ФАЙЛ...")
    missing = failed = False
    for path in rest:
        try:
            source = read_source(path)
        except _SourceError as exc:
            missing = missing or exc.code == EXIT_USAGE
            failed = failed or exc.code == EXIT_COMPILE
            continue
        try:
            check_source(source, "<stdin>" if path == "-" else path, lint_types=True)
        except CompileError as exc:
            _err(exc.format())
            failed = True
            continue
        print(f"{path}: {tr('ok', 'ошибок нет')}")
    if missing:
        return EXIT_USAGE
    return EXIT_COMPILE if failed else EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    _setup_streams()
    if not args:
        _err(_help())
        return EXIT_USAGE
    cmd, rest = args[0], args[1:]
    if cmd in ("help", "-h", "--help"):
        sys.stdout.write(_help())
        return EXIT_OK
    if cmd in ("version", "-V", "--version"):
        print(f"UpsiL {__version__} (Python {platform.python_version()})")
        return EXIT_OK
    if cmd == "run":
        return cmd_run(rest)
    if cmd == "build":
        return cmd_build(rest)
    if cmd == "check":
        return cmd_check(rest)
    if cmd == "test":
        from .testing import main as run_tests
        return run_tests(rest)
    if cmd == "repl":
        from .repl import run_repl
        return run_repl()
    if cmd.endswith(".upl"):
        return cmd_run(args)
    return _usage(f"unknown command '{cmd}'", f"неизвестная команда '{cmd}'")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
