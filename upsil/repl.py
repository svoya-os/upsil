# SPDX-License-Identifier: Apache-2.0
"""``upsil repl``: type UpsiL, see results.

    >>> val x = 21
    >>> x * 2
    42
    >>> fun greet(name) {
    ...     return "Hi, {name}!"
    ... }
    >>> greet("UpsiL")
    "Hi, UpsiL!"

Input continues while a bracket is open or a line ends with an operator;
an empty line forces evaluation. Names may be declared again (the new
declaration replaces the old one). Exit with Ctrl-D or :q.
"""

from __future__ import annotations

import builtins
import copy
import sys
from typing import List, Optional, TextIO

from . import __version__
from .checker import Session
from .errors import CompileError
from .i18n import tr
from .nodes import ClassDecl, FunDecl, Import, PyImport, ResourceDecl, VarDecl


def _declared_names(source: str) -> List[str]:
    from .parser import parse
    try:
        module = parse(source, "<repl>")
    except CompileError:
        return []
    names = []
    for s in module.body:
        if isinstance(s, (VarDecl, ResourceDecl, FunDecl, ClassDecl)):
            names.append(s.name)
        elif isinstance(s, Import):
            names.append(s.alias or s.path[0])
        elif isinstance(s, PyImport):
            names.append(s.alias or s.module.split(".")[0])
    return names


class Repl:
    def __init__(self, out: Optional[TextIO] = None, err: Optional[TextIO] = None):
        self.session = Session()
        self.namespace = {"__name__": "__main__", "__builtins__": builtins}
        self.count = 0
        self.out = out or sys.stdout
        self.err = err or sys.stderr

    def _snapshot(self):
        s = self.session
        return (dict(s.module_block.declared), set(s.module_block.seen), list(s.module_py.locals),
                dict(s.module_py.assigned_outer), set(s.used_names))

    def _restore(self, snap) -> None:
        s = self.session
        (s.module_block.declared, s.module_block.seen, s.module_py.locals,
         s.module_py.assigned_outer, s.used_names) = snap

    def feed(self, source: str, final: bool = False) -> bool:
        """Compile and run one input; False means "incomplete, send more lines"."""
        from .compiler import compile_source
        from .tracebacks import format_runtime_error
        snap = self._snapshot()
        block = self.session.module_block
        for name in _declared_names(source):           # a new declaration replaces the old one
            if name in block.declared:
                old = block.declared.pop(name)
                block.seen.discard(name)
                self.session.module_py.locals = [x for x in self.session.module_py.locals if x is not old]
                self.session.shadowed[name] = old
        self.count += 1
        try:
            program = compile_source(source, f"<repl:{self.count}>", session=self.session, repl=True)
        except CompileError as exc:
            self.session.shadowed = {}
            self._restore(snap)
            if exc.incomplete and not final:
                self.count -= 1
                return False
            self.err.write(exc.format() + "\n")
            return True
        self.session.shadowed = {}
        saved_stdout = sys.stdout
        try:
            sys.stdout = self.out
            exec(program.code, self.namespace)
        except KeyboardInterrupt:
            self.err.write(tr("interrupted", "прервано") + "\n")
        except SystemExit:
            raise
        except BaseException as exc:  # noqa: B902 - shown to the user, the REPL goes on
            self.out.flush()
            self.err.write(format_runtime_error(exc) + "\n")
        finally:
            sys.stdout = saved_stdout
        self.out.flush()
        return True


def run_repl(stdin: Optional[TextIO] = None) -> int:
    stdin = stdin or sys.stdin
    interactive = stdin.isatty() and sys.stdout.isatty()
    if interactive:
        try:
            import readline  # noqa: F401 - line editing and history
        except ImportError:  # pragma: no cover
            pass
        print(f"UpsiL {__version__} REPL. " + tr("Exit: Ctrl-D or :q", "Выход: Ctrl-D или :q"))
    repl = Repl()
    buffer: List[str] = []
    while True:
        prompt = "... " if buffer else ">>> "
        try:
            if interactive:
                line = input(prompt)
            else:
                line = stdin.readline()
                if not line:
                    raise EOFError
                line = line.rstrip("\n")
        except EOFError:
            if buffer:
                repl.feed("\n".join(buffer), final=True)
            if interactive:
                print()
            return 0
        except KeyboardInterrupt:
            print("\n" + tr("interrupted", "прервано"))
            buffer = []
            continue
        if not buffer and line.strip() in (":q", ":quit"):
            return 0
        if not buffer and not line.strip():
            continue
        buffer.append(line)
        try:
            done = repl.feed("\n".join(buffer), final=not line.strip())
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 0
        if done:
            buffer = []
