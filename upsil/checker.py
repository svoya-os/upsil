# SPDX-License-Identifier: Apache-2.0
"""Semantic checks and name resolution.

Scoping rules (docs/spec.md, "Области видимости"):

* Blocks ``{ }`` open a new scope. A name is visible from its declaration to
  the end of its block; using it earlier in the same function is an error.
* A function body may use any name declared in the blocks that enclose the
  function (also further down), because it runs later: this is how
  functions call each other and themselves.
* Re-declaring a name that is visible from an enclosing block of the same
  function (shadowing) is an error; a function may reuse names of outer
  functions and of the module.
* ``val``, parameters, loop variables, functions, classes, imports and
  resources cannot be reassigned. Fields of classes are read and written as
  bare names inside methods (or through ``self``).

The checker annotates the tree in place (``node.sym`` etc.) and decides the
Python name of every symbol: an UpsiL program can legally use one name for two
different things where Python would mix them up (a block-scoped local next to
a global of the same name), so such locals get a fresh Python name (``x_2``).
"""

from __future__ import annotations

import difflib
import os
import re
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from .errors import CompileError, Diagnostic
from .i18n import count_args
from .keywords import BUILTINS, MODULES, PYTHON_ONLY_KEYWORDS, SPECIAL_NAMES
from .nodes import (Arg, Assert, Assign, Attr, AugAssign, BinOp, BoolOp, Break, Call, Catch, ClassDecl,
                    Compare, CompFor, Comprehension, Const, Continue, DestructDecl, DictLit, ExprStmt,
                    For, FunDecl, If, IfExpr, Import, Index, Interp, Lambda, ListLit, Module, Name, Node,
                    Not, Num, Param, Prompt, PyImport, Range, ResourceDecl, Return, Slice, Span, Str,
                    Throw, Try, TupleLit, TypeRef, Unary, UplImport, VarDecl, While, With, WithItem)

_PY_KEYWORDS = frozenset(PYTHON_ONLY_KEYWORDS)
_PY_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")

# (en, ru) words for the kinds of symbols, used in messages
_KIND_WORDS = {
    "val": ("val", "val"),
    "param": ("parameter", "параметр"),
    "loop": ("loop variable", "переменная цикла"),
    "fun": ("function", "функция"),
    "class": ("class", "класс"),
    "model": ("model", "модель"),
    "import": ("imported module", "импортированный модуль"),
    "llm": ("llm resource", "ресурс llm"),
    "vector_store": ("vector_store resource", "ресурс vector_store"),
    "builtin": ("built-in function", "встроенная функция"),
    "self": ("self", "self"),
    "catch": ("caught error", "пойманная ошибка"),
    "with": ("'with ... as' name", "имя из 'with ... as'"),
}

_LITERAL_KINDS_EN = {"int": "an integer", "float": "a float", "str": "a string", "bool": "a boolean",
                     "list": "a list", "dict": "a dict"}
_LITERAL_KINDS_RU = {"int": "целое число", "float": "дробное число", "str": "строка",
                     "bool": "логическое значение", "list": "список", "dict": "словарь"}
_TYPE_ACCEPTS = {"int": {"int"}, "float": {"int", "float"}, "str": {"str"}, "string": {"str"},
                 "bool": {"bool"}, "list": {"list"}, "dict": {"dict"}}


class Symbol:
    """A declared name: a variable, parameter, function, class, import..."""

    def __init__(self, name: str, kind: str, span: Optional[Span] = None, *,
                 mutable: bool = False, params: Optional[List[Tuple[str, bool]]] = None):
        self.name = name
        self.kind = kind              # val var param loop fun class model import llm vector_store
        #                               builtin member self
        self.span = span
        self.mutable = mutable
        self.params = params          # [(name, has_default)] for functions, classes, methods
        self.owner: Optional[PyScope] = None   # the Python scope that holds it (None: builtin)
        self.pyname = name
        self.captured = False         # used by a nested function
        self.fixed = False            # its Python name is part of an interface (parameters)
        self.needs_rename = False
        self.is_field = False         # members: field or method

    def __repr__(self) -> str:
        return f"Symbol({self.name!r}, {self.kind})"


class PyScope:
    """A scope in the generated Python: the module, a function or a class body."""

    def __init__(self, kind: str, parent: Optional["PyScope"]):
        self.kind = kind              # module | function | class
        self.parent = parent          # enclosing scope for Python name lookup (classes skipped)
        self.locals: List[Symbol] = []
        self.assigned_outer: Dict[Symbol, None] = {}   # need `global` / `nonlocal`


class Block:
    """An UpsiL block scope."""

    def __init__(self, parent: Optional["Block"], py: PyScope, kind: str = "block"):
        self.parent = parent
        self.py = py
        self.kind = kind              # block | class
        self.declared: Dict[str, Symbol] = {}
        self.seen: Set[str] = set()


class Session:
    """Module-level state; kept between inputs by the REPL."""

    def __init__(self) -> None:
        self.module_py = PyScope("module", None)
        self.module_block = Block(None, self.module_py)
        self.builtins = {}
        for name in BUILTINS:
            sym = Symbol(name, "builtin")
            sym.fixed = True
            self.builtins[name] = sym
        self.used_names: Set[str] = set(BUILTINS) | set(MODULES)
        # REPL: declarations replaced by the current input; `val x = x + 1` reads the old x
        self.shadowed: Dict[str, Symbol] = {}


class CheckResult:
    def __init__(self, module: Module, session: Session, used_builtins: Set[str], has_models: bool):
        self.module = module
        self.session = session
        self.used_builtins = used_builtins
        self.has_models = has_models


class Checker:
    def __init__(self, filename: str, source: str, *, lint_types: bool = False,
                 session: Optional[Session] = None):
        self.filename = filename
        self.source = source
        self.lint_types = lint_types
        self.session = session or Session()
        self.diags: List[Diagnostic] = []
        self.loop_depth = 0
        self.catch_depth = 0
        self.fun_stack: List[FunDecl] = []
        self.class_stack: List[Block] = []
        self.field_init_block: Optional[Block] = None
        # collected for the renaming pass
        self.refs: List[Tuple[PyScope, Symbol]] = []
        self.implicit_ranges: List[Tuple[PyScope, Range]] = []
        self.pyscopes: List[PyScope] = [self.session.module_py]
        self.symbols: List[Symbol] = []
        self.used_builtins: Set[str] = set()
        self.has_models = False

    # ------------------------------------------------------------------ reporting
    def error(self, span: Span, en: str, ru: str) -> None:
        self.diags.append(Diagnostic(span, en, ru))

    # ------------------------------------------------------------------ entry
    def check(self, module: Module) -> CheckResult:
        self.block_stmts(module.body, self.session.module_block)
        if self.diags:
            raise CompileError(self.diags, self.filename, self.source)
        self.assign_pynames()
        return CheckResult(module, self.session, self.used_builtins, self.has_models)

    # ------------------------------------------------------------------ declarations
    def valid_name(self, name: str, span: Span) -> bool:
        if name in _PY_KEYWORDS:
            self.error(span, f"'{name}' is a reserved word (a Python keyword); choose another name",
                       f"'{name}' — зарезервированное слово (ключевое слово Python); выберите другое имя")
            return False
        if name in SPECIAL_NAMES:
            self.error(span, f"'{name}' is reserved and cannot be declared",
                       f"имя '{name}' зарезервировано, его нельзя объявить")
            return False
        if name.startswith("_upsil"):
            self.error(span, "names that start with '_upsil' are reserved for the compiler",
                       "имена, начинающиеся с '_upsil', зарезервированы для компилятора")
            return False
        return True

    def new_symbol(self, *args, **kwargs) -> Symbol:
        sym = Symbol(*args, **kwargs)
        self.symbols.append(sym)
        self.session.used_names.add(sym.name)
        return sym

    def declare(self, block: Block, sym: Symbol) -> Symbol:
        name = sym.name
        self.valid_name(name, sym.span)
        prev = block.declared.get(name)
        if prev is not None:
            self.error(sym.span, f"'{name}' is already declared in this scope (line {prev.span.line})",
                       f"'{name}' уже объявлено в этой области (строка {prev.span.line})")
            return prev
        if block.kind != "class":
            b = block.parent
            while b is not None and b.py is block.py and b.kind != "class":
                other = b.declared.get(name)
                if other is not None and name in b.seen:
                    self.error(sym.span,
                               f"'{name}' shadows a variable of an enclosing block (line {other.span.line}); "
                               f"choose another name",
                               f"'{name}' перекрывает переменную внешнего блока (строка {other.span.line}); "
                               f"выберите другое имя")
                    break
                b = b.parent
            sym.owner = block.py
            block.py.locals.append(sym)
        block.declared[name] = sym
        return sym

    def predeclare(self, stmts: List[Node], block: Block) -> None:
        for s in stmts:
            if isinstance(s, VarDecl):
                s.sym = self.declare(block, self.new_symbol(s.name, "var" if s.mutable else "val", s.name_span,
                                                            mutable=s.mutable))
            elif isinstance(s, ResourceDecl):
                s.sym = self.declare(block, self.new_symbol(s.name, s.kind, s.name_span))
            elif isinstance(s, FunDecl):
                params = [(p.name, p.default is not None) for p in s.params]
                s.sym = self.declare(block, self.new_symbol(s.name, "fun", s.name_span, params=params))
            elif isinstance(s, ClassDecl):
                params = [(f.name, False) for f in s.fields if f.value is None]
                kind = "model" if s.is_model else "class"
                s.sym = self.declare(block, self.new_symbol(s.name, kind, s.name_span, params=params))
            elif isinstance(s, Import):
                name = s.alias or s.path[0]
                s.sym = self.declare(block, self.new_symbol(name, "import", s.span))
            elif isinstance(s, PyImport):
                name = s.alias or s.module.split(".")[0]
                s.sym = self.declare(block, self.new_symbol(name, "import", s.span))
            elif isinstance(s, UplImport):
                s.sym = self.declare(block, self.new_symbol(s.name, "import", s.span))
            elif isinstance(s, DestructDecl):
                s.syms = []
                seen: Set[str] = set()
                for name, span in zip(s.names, s.name_spans):
                    if name in seen:
                        self.error(span, f"'{name}' is repeated", f"'{name}' повторяется")
                        continue
                    seen.add(name)
                    s.syms.append(self.declare(block, self.new_symbol(name, "var" if s.mutable else "val", span,
                                                                      mutable=s.mutable)))

    # ------------------------------------------------------------------ lookup
    def lookup(self, name: str, block: Block, span: Span, *, report: bool = True) -> Optional[Symbol]:
        self.session.used_names.add(name)
        cur_py = block.py
        b: Optional[Block] = block
        while b is not None:
            sym = b.declared.get(name)
            if sym is not None:
                if b.kind == "class":
                    if self.field_init_block is b and name not in b.seen:
                        self.error(span, f"'{name}' is used before its declaration (line {sym.span.line})",
                                   f"'{name}' используется до объявления (строка {sym.span.line})")
                elif b.py is cur_py and name not in b.seen:
                    previous = self.session.shadowed.get(name) if b is self.session.module_block else None
                    if previous is not None:
                        return previous
                    self.error(span, f"'{name}' is used before its declaration (line {sym.span.line})",
                               f"'{name}' используется до объявления (строка {sym.span.line})")
                return sym
            b = b.parent
        sym = self.session.builtins.get(name)
        if sym is not None:
            return sym
        if not report:
            return None
        if name in _PY_KEYWORDS:
            self.error(span, f"'{name}' is a reserved word (a Python keyword)",
                       f"'{name}' — зарезервированное слово (ключевое слово Python)")
        elif name == "self":
            self.error(span, "'self' is only available inside methods of a class or model",
                       "'self' доступно только внутри методов класса или model")
        else:
            hint_en = hint_ru = ""
            if name in MODULES:
                hint_en = f"; add `import {name}` at the top of the file"
                hint_ru = f"; добавьте `import {name}` в начало файла"
            else:
                close = difflib.get_close_matches(name, self.visible_names(block), n=1, cutoff=0.75)
                if close:
                    hint_en = f"; did you mean '{close[0]}'?"
                    hint_ru = f"; может быть, '{close[0]}'?"
            self.error(span, f"undefined name '{name}'{hint_en}", f"неизвестное имя '{name}'{hint_ru}")
        return None

    def visible_names(self, block: Block) -> List[str]:
        names: List[str] = []
        b: Optional[Block] = block
        while b is not None:
            names.extend(b.declared)
            b = b.parent
        names.extend(self.session.builtins)
        return names

    def note_ref(self, py: PyScope, sym: Symbol) -> None:
        if sym.kind == "member":
            return
        if sym.kind == "builtin":
            self.used_builtins.add(sym.name)
        self.refs.append((py, sym))
        owner = sym.owner
        if owner is not None and owner is not py and owner.kind == "function":
            sym.captured = True

    def use(self, node: Name, block: Block) -> Optional[Symbol]:
        sym = self.lookup(node.name, block, node.span)
        node.sym = sym
        if sym is not None:
            self.note_ref(block.py, sym)
        return sym

    # ------------------------------------------------------------------ statements
    def block_stmts(self, stmts: List[Node], block: Block) -> None:
        self.predeclare(stmts, block)
        for s in stmts:
            self.stmt(s, block)

    def stmt(self, s: Node, block: Block) -> None:
        if isinstance(s, VarDecl):
            if s.value is not None:
                self.expr(s.value, block)
            if self.lint_types:
                self.lint(s.type, s.value, f"'{s.name}'", f"'{s.name}'")
            block.seen.add(s.name)
        elif isinstance(s, ResourceDecl):
            if s.value is not None:
                self.expr(s.value, block)
            block.seen.add(s.name)
        elif isinstance(s, DestructDecl):
            self.expr(s.value, block)
            for name in s.names:
                block.seen.add(name)
        elif isinstance(s, Assign):
            self.expr(s.value, block)
            self.assign_target(s.target, block)
        elif isinstance(s, AugAssign):
            self.expr(s.value, block)
            self.assign_target(s.target, block)
        elif isinstance(s, ExprStmt):
            self.expr(s.expr, block)
        elif isinstance(s, If):
            self.expr(s.cond, block)
            self.block_stmts(s.body, Block(block, block.py))
            if s.orelse:
                self.block_stmts(s.orelse, Block(block, block.py))
        elif isinstance(s, While):
            self.expr(s.cond, block)
            self.loop_depth += 1
            self.block_stmts(s.body, Block(block, block.py))
            self.loop_depth -= 1
        elif isinstance(s, For):
            self.for_stmt(s, block)
        elif isinstance(s, Try):
            self.block_stmts(s.body, Block(block, block.py))
            for c in s.catches:
                if c.type is not None:
                    self.expr(c.type, block)
                cblock = Block(block, block.py)
                if c.name is not None:
                    c.sym = self.declare(cblock, self.new_symbol(c.name, "catch", c.name_span))
                    cblock.seen.add(c.name)
                self.catch_depth += 1
                self.block_stmts(c.body, cblock)
                self.catch_depth -= 1
            if s.final is not None:
                self.block_stmts(s.final, Block(block, block.py))
        elif isinstance(s, Throw):
            if s.value is not None:
                self.expr(s.value, block)
            elif self.catch_depth == 0:
                self.error(s.span, "a bare 'throw' re-throws the caught error, so it belongs inside catch { }; "
                                   "otherwise write throw \"what went wrong\"",
                           "'throw' без значения повторно бросает пойманную ошибку и допустим только внутри "
                           "catch { }; иначе пишите throw \"что случилось\"")
        elif isinstance(s, With):
            body = Block(block, block.py)
            names: Set[str] = set()
            for item in s.items:
                self.expr(item.expr, block)
            for item in s.items:
                if item.name is None:
                    continue
                if item.name in names:
                    self.error(item.name_span, f"'{item.name}' is repeated", f"'{item.name}' повторяется")
                    continue
                names.add(item.name)
                item.sym = self.declare(body, self.new_symbol(item.name, "with", item.name_span))
                body.seen.add(item.name)
            self.block_stmts(s.body, body)
        elif isinstance(s, Assert):
            self.expr(s.cond, block)
            if s.message is not None:
                self.expr(s.message, block)
        elif isinstance(s, (Break, Continue)):
            if self.loop_depth == 0:
                word = "break" if isinstance(s, Break) else "continue"
                self.error(s.span, f"'{word}' outside a loop", f"'{word}' вне цикла")
        elif isinstance(s, Return):
            if not self.fun_stack:
                self.error(s.span, "'return' outside a function", "'return' вне функции")
            elif s.value is not None:
                self.expr(s.value, block)
                fn = self.fun_stack[-1]
                if self.lint_types:
                    self.lint(fn.ret, s.value, f"the result of {fn.name}()", f"результата {fn.name}()")
        elif isinstance(s, FunDecl):
            block.seen.add(s.name)
            self.function(s, block)
        elif isinstance(s, ClassDecl):
            if block is not self.session.module_block:
                self.error(s.span, "classes and models can only be declared at the top level of a file",
                           "классы и модели можно объявлять только на верхнем уровне файла")
            block.seen.add(s.name)
            self.class_decl(s, block)
        elif isinstance(s, (Import, PyImport, UplImport)):
            if block is not self.session.module_block:
                self.error(s.span, "import is only allowed at the top level of a file",
                           "import допускается только на верхнем уровне файла")
            self.check_import(s)
            if s.sym is not None:
                block.seen.add(s.sym.name)
        else:  # pragma: no cover - the parser produces nothing else
            raise AssertionError(f"unknown statement {type(s).__name__}")

    def for_stmt(self, s: For, block: Block) -> None:
        self.expr(s.iter, block)
        body = Block(block, block.py)
        s.syms = []
        names: Set[str] = set()
        for name, span in zip(s.names, s.name_spans):
            if name in names:
                self.error(span, f"loop variable '{name}' is repeated", f"переменная цикла '{name}' повторяется")
                continue
            names.add(name)
            sym = self.declare(body, self.new_symbol(name, "loop", span))
            body.seen.add(name)
            s.syms.append(sym)
        self.loop_depth += 1
        self.block_stmts(s.body, body)
        self.loop_depth -= 1

    def base_dir(self) -> str:
        """The folder imports are relative to: the program's folder (the current one for stdin and the REPL)."""
        if self.filename.startswith("<"):
            return os.getcwd()
        return os.path.dirname(os.path.abspath(self.filename))

    def check_import(self, s: Node) -> None:
        if isinstance(s, UplImport):
            full = os.path.normpath(os.path.join(self.base_dir(), s.path))
            if not os.path.isfile(full):
                self.error(s.span, f"file not found: {s.path} (looked in {os.path.dirname(full)})",
                           f"файл не найден: {s.path} (искали в {os.path.dirname(full)})")
            return
        if isinstance(s, Import):
            root = s.path[0]
            if root not in MODULES and len(s.path) == 1 and os.path.isfile(os.path.join(self.base_dir(), root + ".upl")):
                s.upl_path = root + ".upl"     # import helpers  ->  helpers.upl next to the program
                return
            if root not in MODULES:
                dotted = ".".join(s.path)
                self.error(s.span,
                           f"unknown module '{root}'. UpsiL modules: {', '.join(MODULES)}. "
                           f"For a Python module write: import py \"{dotted}\"",
                           f"неизвестный модуль '{root}'. Модули UpsiL: {', '.join(MODULES)}. "
                           f"Модуль Python подключается так: import py \"{dotted}\"")
            elif len(s.path) > 2:
                self.error(s.span, "import at most one level deep, e.g. import nn.functional as F",
                           "импорт не глубже одного уровня, например import nn.functional as F")
        else:
            if not _PY_MODULE_RE.match(s.module):
                self.error(s.span, f"'{s.module}' is not a valid Python module name",
                           f"'{s.module}' — недопустимое имя модуля Python")

    def assign_target(self, target: Node, block: Block) -> None:
        if isinstance(target, TupleLit):
            for item in target.items:
                self.assign_target(item, block)
            return
        if isinstance(target, Name):
            sym = self.lookup(target.name, block, target.span, report=False)
            target.sym = sym
            if sym is None:
                if target.name in _PY_KEYWORDS:
                    self.valid_name(target.name, target.span)
                else:
                    self.error(target.span,
                               f"cannot assign to undeclared '{target.name}'; declare it first: var {target.name} = ...",
                               f"нельзя присвоить необъявленной переменной '{target.name}'; "
                               f"объявите её: var {target.name} = ...")
                return
            if not self.assignable(sym, target.span):
                return
            if sym.kind == "member":
                return
            py = block.py
            if sym.owner is not None and sym.owner is not py:
                py.assigned_outer[sym] = None
            self.note_ref(py, sym)
        elif isinstance(target, Attr):
            self.expr(target.obj, block)
            obj_sym = target.obj.sym if isinstance(target.obj, Name) else None
            if obj_sym is not None and obj_sym.kind == "self" and self.class_stack:
                member = self.class_stack[-1].declared.get(target.name)
                if member is not None:
                    self.assignable(member, target.name_span)
        elif isinstance(target, Index):
            self.expr(target, block)

    def assignable(self, sym: Symbol, span: Span) -> bool:
        k = sym.kind
        line = sym.span.line if sym.span is not None else 0
        if k == "var":
            return True
        if k == "member":
            if not sym.is_field:
                self.error(span, f"cannot assign to method '{sym.name}'", f"нельзя присвоить методу '{sym.name}'")
                return False
            if not sym.mutable:
                self.error(span, f"cannot reassign val field '{sym.name}' (line {line}); declare it with var",
                           f"нельзя изменить поле val '{sym.name}' (строка {line}); объявите его через var")
                return False
            return True
        if k in ("val", "llm", "vector_store"):
            self.error(span, f"cannot reassign val '{sym.name}' (declared at line {line}); declare it with var",
                       f"нельзя изменить val '{sym.name}' (объявлено в строке {line}); объявите через var")
            return False
        if k == "param":
            self.error(span, f"cannot assign to parameter '{sym.name}': parameters are read-only "
                             f"(make a copy: var {sym.name}2 = {sym.name})",
                       f"нельзя изменить параметр '{sym.name}': параметры только для чтения "
                       f"(сделайте копию: var {sym.name}2 = {sym.name})")
            return False
        word_en, word_ru = _KIND_WORDS.get(k, (k, k))
        self.error(span, f"cannot assign to {word_en} '{sym.name}'", f"нельзя присвоить: '{sym.name}' — {word_ru}")
        return False

    # ------------------------------------------------------------------ functions and classes
    @staticmethod
    def py_parent(py: PyScope) -> PyScope:
        return py.parent if py.kind == "class" else py

    def new_pyscope(self, kind: str, parent: Optional[PyScope]) -> PyScope:
        py = PyScope(kind, parent)
        self.pyscopes.append(py)
        return py

    def self_symbol(self, py: PyScope, span: Span) -> Symbol:
        sym = self.new_symbol("self", "self", span)
        sym.owner = py
        sym.fixed = True
        py.locals.append(sym)
        return sym

    def function(self, fn: FunDecl, block: Block, *, method: bool = False) -> None:
        py = self.new_pyscope("function", self.py_parent(block.py))
        fn.scope = py
        fblock = Block(block, py)
        if method:
            fn.is_method = True
            fblock.declared["self"] = self.self_symbol(py, fn.name_span)
            fblock.seen.add("self")
        names: Set[str] = set()
        had_default = False
        for p in fn.params:
            if p.name in names:
                self.error(p.span, f"duplicate parameter '{p.name}'", f"параметр '{p.name}' повторяется")
                continue
            names.add(p.name)
            if p.default is None and had_default:
                self.error(p.span, f"parameter '{p.name}' without a default follows a parameter with a default",
                           f"параметр '{p.name}' без значения по умолчанию идёт после параметра со значением")
            had_default = had_default or p.default is not None
            p.sym = self.declare(fblock, self.new_symbol(p.name, "param", p.span))
            p.sym.fixed = True
        for p in fn.params:
            if p.default is not None:
                self.expr(p.default, fblock)
                if self.lint_types:
                    self.lint(p.type, p.default, f"parameter '{p.name}'", f"параметра '{p.name}'")
            fblock.seen.add(p.name)
        saved_loop, saved_catch = self.loop_depth, self.catch_depth
        self.loop_depth = self.catch_depth = 0
        self.fun_stack.append(fn)
        self.block_stmts(fn.body, fblock)
        self.fun_stack.pop()
        self.loop_depth, self.catch_depth = saved_loop, saved_catch

    def class_decl(self, cls: ClassDecl, block: Block) -> None:
        if cls.is_model:
            self.has_models = True
        cpy = self.new_pyscope("class", block.py)
        cblock = Block(block, cpy, kind="class")
        for f in cls.fields:
            sym = self.new_symbol(f.name, "member", f.name_span, mutable=f.mutable)
            sym.is_field = True
            f.sym = self.declare(cblock, sym)
        for m in cls.methods:
            params = [(p.name, p.default is not None) for p in m.params]
            m.sym = self.declare(cblock, self.new_symbol(m.name, "member", m.name_span, params=params))
            cblock.seen.add(m.name)
        if cls.is_model and not any(m.name == "forward" for m in cls.methods):
            self.error(cls.name_span, f"model '{cls.name}' has no forward(...) method",
                       f"у model '{cls.name}' нет метода forward(...)")
        # field initializers run in the generated __init__, in order
        init_py = self.new_pyscope("function", self.py_parent(cpy))
        cls.init_scope = init_py
        iblock = Block(cblock, init_py)
        iblock.declared["self"] = self.self_symbol(init_py, cls.name_span)
        iblock.seen.add("self")
        for f in cls.fields:
            if f.value is None:
                ctor = self.new_symbol(f.name, "param", f.name_span)
                ctor.owner = init_py
                ctor.fixed = True
                init_py.locals.append(ctor)
        self.class_stack.append(cblock)
        self.field_init_block = cblock
        for f in cls.fields:
            if f.value is not None:
                self.expr(f.value, iblock)
                if self.lint_types:
                    self.lint(f.type, f.value, f"'{f.name}'", f"'{f.name}'")
            cblock.seen.add(f.name)
        self.field_init_block = None
        saved = self.fun_stack
        self.fun_stack = []
        for m in cls.methods:
            self.function(m, cblock, method=True)
        self.fun_stack = saved
        self.class_stack.pop()

    # ------------------------------------------------------------------ expressions
    def expr(self, node: Node, block: Block) -> None:
        t = type(node)
        if t is Name:
            self.use(node, block)
        elif t is Num or t is Const:
            return
        elif t is Str:
            for p in node.parts:
                if isinstance(p, Interp):
                    self.expr(p.expr, block)
        elif t is ListLit:
            for item in node.items:
                self.expr(item, block)
        elif t is DictLit:
            for k, v in node.items:
                self.expr(k, block)
                self.expr(v, block)
        elif t is Unary or t is Not:
            self.expr(node.operand, block)
        elif t is BinOp or t is BoolOp or t is Compare:
            self.expr(node.left, block)
            self.expr(node.right, block)
        elif t is Range:
            self.expr(node.start, block)
            self.expr(node.end, block)
            self.implicit_ranges.append((block.py, node))
        elif t is Call:
            self.call(node, block)
        elif t is Index:
            self.expr(node.obj, block)
            for item in node.items:
                self.expr(item, block)
        elif t is Slice:
            for part in (node.lo, node.hi, node.step):
                if part is not None:
                    self.expr(part, block)
        elif t is Attr:
            self.session.used_names.add(node.name)
            self.expr(node.obj, block)
        elif t is Prompt:
            self.expr(node.model, block)
            if node.system is not None:
                self.expr(node.system, block)
            self.expr(node.text, block)
            if node.schema is not None:
                self.expr(node.schema, block)
        elif t is TupleLit:
            for item in node.items:
                self.expr(item, block)
        elif t is IfExpr:
            self.expr(node.cond, block)
            self.expr(node.then, block)
            self.expr(node.orelse, block)
        elif t is Lambda:
            self.lambda_expr(node, block)
        elif t is Comprehension:
            self.comprehension(node, block)
        else:  # pragma: no cover
            raise AssertionError(f"unknown expression {t.__name__}")

    def lambda_expr(self, node: Lambda, block: Block) -> None:
        py = self.new_pyscope("function", self.py_parent(block.py))
        node.scope = py
        lblock = Block(block, py)
        names: Set[str] = set()
        for p in node.params:
            if p.name in names:
                self.error(p.span, f"duplicate parameter '{p.name}'", f"параметр '{p.name}' повторяется")
                continue
            names.add(p.name)
            p.sym = self.declare(lblock, self.new_symbol(p.name, "param", p.span))
            p.sym.fixed = True
            lblock.seen.add(p.name)
        self.expr(node.body, lblock)

    def comprehension(self, node: Comprehension, block: Block) -> None:
        # Python runs a comprehension in its own function scope; the first iterable is
        # evaluated outside of it.
        py = self.new_pyscope("function", self.py_parent(block.py))
        node.scope = py
        inner = Block(block, py)
        for i, clause in enumerate(node.fors):
            self.expr(clause.iter, block if i == 0 else inner)
            clause.syms = []
            for name, span in zip(clause.names, clause.name_spans):
                if name in inner.declared:
                    self.error(span, f"'{name}' is repeated", f"'{name}' повторяется")
                    continue
                sym = self.declare(inner, self.new_symbol(name, "loop", span))
                inner.seen.add(name)
                clause.syms.append(sym)
            for cond in clause.conds:
                self.expr(cond, inner)
        self.expr(node.elt, inner)
        if node.value is not None:
            self.expr(node.value, inner)

    def call(self, node: Call, block: Block) -> None:
        self.expr(node.func, block)
        for a in node.args:
            self.expr(a.value, block)
        f = node.func
        if isinstance(f, Name) and f.sym is not None and f.sym.params is not None:
            self.check_arity(node, f.name, f.sym.params)

    def check_arity(self, node: Call, fname: str, params: List[Tuple[str, bool]]) -> None:
        positional = [a for a in node.args if a.name is None]
        named = [a for a in node.args if a.name is not None]
        if len(positional) > len(params):
            n_en, n_ru = count_args(len(params))
            got = len(positional)
            self.error(node.span, f"{fname}() takes {n_en} but {got} {'was' if got == 1 else 'were'} given",
                       f"{fname}() принимает {n_ru}, а получено аргументов: {got}")
            return
        names = [p[0] for p in params]
        bound = set(names[:len(positional)])
        for a in named:
            if a.name not in names:
                self.error(a.span, f"{fname}() has no parameter '{a.name}'", f"у {fname}() нет параметра '{a.name}'")
                return
            if a.name in bound:
                self.error(a.span, f"{fname}() got the argument '{a.name}' twice",
                           f"в {fname}() аргумент '{a.name}' передан дважды")
                return
            bound.add(a.name)
        for pname, has_default in params:
            if not has_default and pname not in bound:
                self.error(node.span, f"{fname}() is missing the argument '{pname}'",
                           f"в вызове {fname}() не хватает аргумента '{pname}'")
                return

    # ------------------------------------------------------------------ type lint (upsil check)
    def lint(self, typ: Optional[TypeRef], value: Optional[Node], what_en: str, what_ru: str) -> None:
        if typ is None or value is None:
            return
        accepts = _TYPE_ACCEPTS.get(typ.name)
        if accepts is None:
            return
        kind = literal_kind(value)
        if kind is None or kind in accepts:
            return
        self.error(value.span,
                   f"type mismatch: {what_en} is declared as {typ.name} but the value is {_LITERAL_KINDS_EN[kind]}",
                   f"несовпадение типов: у {what_ru} указан тип {typ.name}, а значение — {_LITERAL_KINDS_RU[kind]}")

    # ------------------------------------------------------------------ Python names
    def fresh(self, name: str) -> str:
        used = self.session.used_names
        k = 2
        while f"{name}_{k}" in used:
            k += 1
        new = f"{name}_{k}"
        used.add(new)
        return new

    def assign_pynames(self) -> None:
        by_name: Dict[PyScope, Dict[str, List[Symbol]]] = {}

        def locals_named(py: PyScope, name: str) -> List[Symbol]:
            table = by_name.get(py)
            if table is None:
                table = defaultdict(list)
                for loc in py.locals:
                    table[loc.name].append(loc)
                by_name[py] = table
            return table.get(name, [])

        # A reference must reach its symbol: rename same-named locals in between.
        for py, sym in self.refs:
            scope: Optional[PyScope] = py
            while scope is not None and scope is not sym.owner:
                for loc in locals_named(scope, sym.name):
                    if loc is not sym and not loc.fixed:
                        loc.needs_rename = True
                scope = scope.parent
        # `a..b` compiles to range(a, b): make sure `range` is the builtin there.
        for py, node in self.implicit_ranges:
            scope = py
            while scope is not None:
                for loc in locals_named(scope, "range"):
                    if loc.fixed:
                        node.prelude_range = True
                    else:
                        loc.needs_rename = True
                scope = scope.parent
        # Two block-scoped locals with one name in one function, one of them
        # used by a closure: give them separate Python variables.
        for py in self.pyscopes:
            groups: Dict[str, List[Symbol]] = defaultdict(list)
            for loc in py.locals:
                groups[loc.name].append(loc)
            for syms in groups.values():
                if len(syms) > 1 and any(s.captured for s in syms):
                    for s in syms[1:]:
                        if not s.fixed:
                            s.needs_rename = True
        for sym in self.symbols:
            if sym.needs_rename and not sym.fixed:
                sym.pyname = self.fresh(sym.name)
                sym.needs_rename = False
            sym.fixed = sym.fixed or sym.owner is self.session.module_py


def literal_kind(node: Node) -> Optional[str]:
    if isinstance(node, Unary) and isinstance(node.operand, Num):
        node = node.operand
    if isinstance(node, Num):
        return "float" if isinstance(node.value, float) else "int"
    if isinstance(node, Str):
        return "str"
    if isinstance(node, Const):
        return None if node.value is None else "bool"
    if isinstance(node, ListLit):
        return "list"
    if isinstance(node, DictLit):
        return "dict"
    return None


def check(module: Module, filename: str, source: str, *, lint_types: bool = False,
          session: Optional[Session] = None) -> CheckResult:
    return Checker(filename, source, lint_types=lint_types, session=session).check(module)
