# SPDX-License-Identifier: Apache-2.0
"""Code generation: checked UpsiL tree -> Python ``ast.Module``.

Every generated node carries the line and column of the UpsiL code it came
from, so the compiled program reports errors at ``file.upl:line``. Nothing is
generated as text: string literals become ``ast.Constant`` and interpolations
become expressions compiled from the UpsiL tree, so user text is never
evaluated as code.

Helpers come from ``upsil.runtime.prelude``, imported as ``_upsil`` (the
``_upsil`` prefix is reserved, so it cannot clash with user names).
"""

from __future__ import annotations

import ast
from typing import List, Optional

from .checker import CheckResult, PyScope, Symbol
from .keywords import PRELUDE_BUILTINS, PYTHON_ONLY_KEYWORDS
from .nodes import (Assert, Assign, Attr, AugAssign, BinOp, BoolOp, Break, Call, ClassDecl, Compare,
                    Comprehension, Const, Continue, DestructDecl, DictLit, ExprStmt, For, FunDecl, If,
                    IfExpr, Import, Index, Interp, Lambda, ListLit, Module, Name, Node, Not, Num, Prompt,
                    PyImport, Range, ResourceDecl, Return, Slice, Span, Str, Throw, Try, TupleLit,
                    TypeRef, Unary, UplImport, VarDecl, While, With)

_BINOPS = {"+": ast.Add, "-": ast.Sub, "*": ast.Mult, "/": ast.Div, "%": ast.Mod,
           "@": ast.MatMult, "**": ast.Pow}
_CMPOPS = {"==": ast.Eq, "!=": ast.NotEq, "<": ast.Lt, "<=": ast.LtE, ">": ast.Gt, ">=": ast.GtE,
           "in": ast.In, "not in": ast.NotIn}
_HAS_TYPE_PARAMS = "type_params" in ast.FunctionDef._fields
_PY_KEYWORDS = frozenset(PYTHON_ONLY_KEYWORDS)


def _is_constant(node: Node) -> bool:
    if isinstance(node, Unary) and isinstance(node.operand, Num):
        return True
    if isinstance(node, Str):
        return node.is_plain
    return isinstance(node, (Num, Const))


def _contains_str(node: Node) -> bool:
    """True if a string literal appears anywhere inside ``node``."""
    if isinstance(node, Str):
        return True
    for value in vars(node).values():
        if isinstance(value, Node) and _contains_str(value):
            return True
        if isinstance(value, list):
            for item in value:
                if isinstance(item, Node) and _contains_str(item):
                    return True
                if isinstance(item, tuple) and any(isinstance(x, Node) and _contains_str(x) for x in item):
                    return True
    return False


class Codegen:
    def __init__(self, result: CheckResult, source: str, *, repl: bool = False):
        self.result = result
        self.lines = source.split("\n")
        self.repl = repl
        self.need_prelude = False
        self.need_nn = False
        self.need_future = False
        self.prelude_names: set = set()
        self.depth = 0

    # ------------------------------------------------------------------ positions
    def bcol(self, line: int, col: int) -> int:
        """UTF-8 byte offset of 1-based character column ``col`` (what CPython expects)."""
        if 1 <= line <= len(self.lines):
            return len(self.lines[line - 1][:max(col - 1, 0)].encode("utf-8"))
        return max(col - 1, 0)

    def at(self, node, span: Span):
        node.lineno = span.line
        node.col_offset = self.bcol(span.line, span.col)
        node.end_lineno = span.end_line
        node.end_col_offset = self.bcol(span.end_line, span.end_col)
        if (node.end_lineno, node.end_col_offset) < (node.lineno, node.col_offset):
            node.end_lineno, node.end_col_offset = node.lineno, node.col_offset
        return node

    def mk(self, cls, span: Span, **fields):
        return self.at(cls(**fields), span)

    def load(self, name: str, span: Span) -> ast.Name:
        return self.mk(ast.Name, span, id=name, ctx=ast.Load())

    def prelude(self, attr: str, span: Span) -> ast.Attribute:
        self.need_prelude = True
        return self.mk(ast.Attribute, span, value=self.load("_upsil", span), attr=attr, ctx=ast.Load())

    def call(self, func, args: list, span: Span, keywords: Optional[list] = None) -> ast.Call:
        return self.mk(ast.Call, span, func=func, args=args, keywords=keywords or [])

    def self_attr(self, name: str, span: Span, ctx=None) -> ast.Attribute:
        return self.mk(ast.Attribute, span, value=self.load("self", span), attr=name, ctx=ctx or ast.Load())

    # ------------------------------------------------------------------ module
    def module(self, mod: Module) -> ast.Module:
        body = self.stmts(mod.body)
        top = Span(1, 1, 1, 1)
        header: List[ast.stmt] = []
        if self.need_future:
            header.append(self.mk(ast.ImportFrom, top, module="__future__",
                                  names=[ast.alias(name="annotations")], level=0))
        if self.need_prelude:
            header.append(self.mk(ast.ImportFrom, top, module="upsil.runtime",
                                  names=[ast.alias(name="prelude", asname="_upsil")], level=0))
        if self.prelude_names:
            header.append(self.mk(ast.ImportFrom, top, module="upsil.runtime.prelude",
                                  names=[ast.alias(name=n) for n in sorted(self.prelude_names)], level=0))
        if self.need_nn:
            header.append(self.mk(ast.ImportFrom, top, module="upsil.runtime",
                                  names=[ast.alias(name="nn", asname="_upsil_nn")], level=0))
        tree = ast.Module(body=header + body, type_ignores=[])
        ast.fix_missing_locations(tree)
        return tree

    # ------------------------------------------------------------------ statements
    def stmts(self, stmts: List[Node]) -> List[ast.stmt]:
        out: List[ast.stmt] = []
        for s in stmts:
            out.extend(getattr(self, "s_" + type(s).__name__)(s))
        return out

    def body(self, stmts: List[Node], span: Span) -> List[ast.stmt]:
        return self.stmts(stmts) or [self.mk(ast.Pass, span)]

    def s_VarDecl(self, s: VarDecl) -> list:
        target = self.mk(ast.Name, s.name_span, id=s.sym.pyname, ctx=ast.Store())
        value = self.expr(s.value) if s.value is not None else self.mk(ast.Constant, s.span, value=None)
        if s.type is not None:
            return [self.mk(ast.AnnAssign, s.span, target=target, annotation=self.type_expr(s.type),
                            value=value, simple=1)]
        return [self.mk(ast.Assign, s.span, targets=[target], value=value)]

    def s_ResourceDecl(self, s: ResourceDecl) -> list:
        helper = "llm_resource" if s.kind == "llm" else "store_resource"
        args = [self.mk(ast.Constant, s.name_span, value=s.name)]
        if s.value is not None:
            args.append(self.expr(s.value))
        target = self.mk(ast.Name, s.name_span, id=s.sym.pyname, ctx=ast.Store())
        return [self.mk(ast.Assign, s.span, targets=[target], value=self.call(self.prelude(helper, s.span), args, s.span))]

    def s_DestructDecl(self, s: DestructDecl) -> list:
        names = [self.mk(ast.Name, span, id=sym.pyname, ctx=ast.Store()) for sym, span in zip(s.syms, s.name_spans)]
        target = self.mk(ast.Tuple, s.name_spans[0].to(s.name_spans[-1]), elts=names, ctx=ast.Store())
        return [self.mk(ast.Assign, s.span, targets=[target], value=self.expr(s.value))]

    def s_Try(self, s: Try) -> list:
        handlers = []
        for c in s.catches:
            typ = self.expr(c.type) if c.type is not None else self.prelude("Error", c.span)
            body = self.body(c.body, c.span)
            name = None
            if c.name is not None:
                # Python deletes an `except ... as` name when the handler ends, which would break
                # a lambda that captured it: catch into a hidden name and copy it to the user's.
                name = "_upsil_err"
                copy = self.mk(ast.Assign, c.name_span,
                               targets=[self.mk(ast.Name, c.name_span, id=c.sym.pyname, ctx=ast.Store())],
                               value=self.load("_upsil_err", c.name_span))
                body = [copy] + body
            handlers.append(self.mk(ast.ExceptHandler, c.span, type=typ, name=name, body=body))
        final = self.body(s.final, s.span) if s.final is not None else []
        return [self.mk(ast.Try, s.span, body=self.body(s.body, s.span), handlers=handlers, orelse=[],
                        finalbody=final)]

    def s_Throw(self, s: Throw) -> list:
        if s.value is None:
            return [self.mk(ast.Raise, s.span, exc=None, cause=None)]
        exc = self.call(self.prelude("to_error", s.value.span), [self.expr(s.value)], s.value.span)
        return [self.mk(ast.Raise, s.span, exc=exc, cause=None)]

    def s_With(self, s: With) -> list:
        items = []
        for item in s.items:
            var = None
            if item.name is not None:
                var = self.mk(ast.Name, item.name_span, id=item.sym.pyname, ctx=ast.Store())
            items.append(ast.withitem(context_expr=self.expr(item.expr), optional_vars=var))
        return [self.mk(ast.With, s.span, items=items, body=self.body(s.body, s.span), type_comment=None)]

    def s_Assert(self, s: Assert) -> list:
        # not Python's assert: `python -O` would drop it
        text = self.source_text(s.cond.span)
        message = self.expr(s.message) if s.message is not None else self.mk(ast.Constant, s.span, value=None)
        exc = self.call(self.prelude("assertion_failed", s.span),
                        [message, self.mk(ast.Constant, s.cond.span, value=text)], s.span)
        test = self.mk(ast.UnaryOp, s.cond.span, op=ast.Not(), operand=self.expr(s.cond))
        return [self.mk(ast.If, s.span, test=test, body=[self.mk(ast.Raise, s.span, exc=exc, cause=None)], orelse=[])]

    def source_text(self, span: Span) -> str:
        if not 1 <= span.line <= len(self.lines):
            return ""
        if span.end_line == span.line:
            return self.lines[span.line - 1][span.col - 1:span.end_col - 1]
        parts = [self.lines[span.line - 1][span.col - 1:]]
        parts += self.lines[span.line:span.end_line - 1]
        parts.append(self.lines[span.end_line - 1][:span.end_col - 1])
        return " ".join(p.strip() for p in parts)

    def upl_import(self, path: str, pyname: str, span: Span) -> list:
        value = self.call(self.prelude("import_upl", span), [self.mk(ast.Constant, span, value=path)], span)
        target = self.mk(ast.Name, span, id=pyname, ctx=ast.Store())
        return [self.mk(ast.Assign, span, targets=[target], value=value)]

    def s_UplImport(self, s: UplImport) -> list:
        return self.upl_import(s.path, s.sym.pyname, s.span)

    def s_Assign(self, s: Assign) -> list:
        return [self.mk(ast.Assign, s.span, targets=[self.target(s.target)], value=self.expr(s.value))]

    def s_AugAssign(self, s: AugAssign) -> list:
        return [self.mk(ast.AugAssign, s.span, target=self.target(s.target), op=_BINOPS[s.op](),
                        value=self.expr(s.value))]

    def target(self, t: Node):
        if isinstance(t, TupleLit):
            return self.mk(ast.Tuple, t.span, elts=[self.target(i) for i in t.items], ctx=ast.Store())
        if isinstance(t, Name):
            if t.sym.kind == "member":
                return self.self_attr(t.sym.name, t.span, ast.Store())
            return self.mk(ast.Name, t.span, id=t.sym.pyname, ctx=ast.Store())
        if isinstance(t, Attr):
            return self.mk(ast.Attribute, t.span, value=self.expr(t.obj), attr=t.name, ctx=ast.Store())
        assert isinstance(t, Index)
        return self.mk(ast.Subscript, t.span, value=self.expr(t.obj), slice=self.subscript(t), ctx=ast.Store())

    def s_ExprStmt(self, s: ExprStmt) -> list:
        value = self.expr(s.expr)
        if self.repl and self.depth == 0:
            value = self.call(self.prelude("repl_show", s.span), [value], s.span)
        return [self.mk(ast.Expr, s.span, value=value)]

    def s_If(self, s: If) -> list:
        return [self.mk(ast.If, s.span, test=self.expr(s.cond), body=self.body(s.body, s.span),
                        orelse=self.stmts(s.orelse))]

    def s_While(self, s: While) -> list:
        return [self.mk(ast.While, s.span, test=self.expr(s.cond), body=self.body(s.body, s.span), orelse=[])]

    def s_For(self, s: For) -> list:
        names = [self.mk(ast.Name, span, id=sym.pyname, ctx=ast.Store())
                 for sym, span in zip(s.syms, s.name_spans)]
        if len(names) == 1:
            target = names[0]
        else:
            target = self.mk(ast.Tuple, s.name_spans[0].to(s.name_spans[-1]), elts=names, ctx=ast.Store())
        return [self.mk(ast.For, s.span, target=target, iter=self.expr(s.iter), body=self.body(s.body, s.span),
                        orelse=[], type_comment=None)]

    def s_Break(self, s: Break) -> list:
        return [self.mk(ast.Break, s.span)]

    def s_Continue(self, s: Continue) -> list:
        return [self.mk(ast.Continue, s.span)]

    def s_Return(self, s: Return) -> list:
        value = self.expr(s.value) if s.value is not None else None
        return [self.mk(ast.Return, s.span, value=value)]

    def s_FunDecl(self, fn: FunDecl) -> list:
        return [self.function_def(fn, fn.sym.pyname)]

    def s_ClassDecl(self, cls: ClassDecl) -> list:
        if cls.is_model:
            self.need_nn = True
            base = self.mk(ast.Attribute, cls.name_span, value=self.load("_upsil_nn", cls.name_span),
                           attr="Module", ctx=ast.Load())
        else:
            base = self.prelude("Object", cls.name_span)
        body: List[ast.stmt] = []
        init = self.init_def(cls)
        if init is not None:
            body.append(init)
        for m in cls.methods:
            body.append(self.function_def(m, m.name))
        node = ast.ClassDef(name=cls.sym.pyname, bases=[base], keywords=[],
                            body=body or [self.mk(ast.Pass, cls.span)], decorator_list=[])
        if _HAS_TYPE_PARAMS:
            node.type_params = []
        return [self.at(node, cls.span)]

    def s_Import(self, s: Import) -> list:
        path = s.path
        pyname = s.sym.pyname
        upl = getattr(s, "upl_path", None)
        if upl is not None:
            return self.upl_import(upl, pyname, s.span)
        if len(path) == 2 and s.alias:
            names = [ast.alias(name=path[1], asname=pyname)]
            return [self.mk(ast.ImportFrom, s.span, module=f"upsil.runtime.{path[0]}", names=names, level=0)]
        names = [ast.alias(name=path[0], asname=None if pyname == path[0] else pyname)]
        return [self.mk(ast.ImportFrom, s.span, module="upsil.runtime", names=names, level=0)]

    def s_PyImport(self, s: PyImport) -> list:
        pyname = s.sym.pyname
        first = s.module.split(".")[0]
        if s.alias:
            return [self.mk(ast.Import, s.span, names=[ast.alias(name=s.module, asname=pyname)])]
        if pyname == first:
            return [self.mk(ast.Import, s.span, names=[ast.alias(name=s.module)])]
        value = self.call(self.prelude("py_import", s.span), [self.mk(ast.Constant, s.span, value=s.module)], s.span)
        target = self.mk(ast.Name, s.span, id=pyname, ctx=ast.Store())
        return [self.mk(ast.Assign, s.span, targets=[target], value=value)]

    # ------------------------------------------------------------------ functions and classes
    def scope_decls(self, py: PyScope, span: Span) -> List[ast.stmt]:
        outer = list(py.assigned_outer)
        glob = [s.pyname for s in outer if s.owner is not None and s.owner.kind == "module"]
        nonloc = [s.pyname for s in outer if s.owner is not None and s.owner.kind == "function"]
        out: List[ast.stmt] = []
        if glob:
            out.append(self.mk(ast.Global, span, names=glob))
        if nonloc:
            out.append(self.mk(ast.Nonlocal, span, names=nonloc))
        return out

    def function_def(self, fn: FunDecl, name: str) -> ast.FunctionDef:
        args: List[ast.arg] = []
        defaults: List[ast.expr] = []
        prologue: List[ast.stmt] = []
        if fn.is_method:
            args.append(self.mk(ast.arg, fn.name_span, arg="self", annotation=None))
        self.depth += 1
        for p in fn.params:
            annotation = self.type_expr(p.type) if p.type is not None else None
            args.append(self.mk(ast.arg, p.span, arg=p.sym.pyname, annotation=annotation))
            if p.default is None:
                continue
            if _is_constant(p.default):
                defaults.append(self.expr(p.default))
                continue
            # evaluated at every call, like in Kotlin, and may use earlier parameters
            defaults.append(self.prelude("MISSING", p.default.span))
            test = self.mk(ast.Compare, p.span, left=self.load(p.sym.pyname, p.span), ops=[ast.Is()],
                           comparators=[self.prelude("MISSING", p.span)])
            assign = self.mk(ast.Assign, p.default.span,
                             targets=[self.mk(ast.Name, p.span, id=p.sym.pyname, ctx=ast.Store())],
                             value=self.expr(p.default))
            prologue.append(self.mk(ast.If, p.span, test=test, body=[assign], orelse=[]))
        body = self.scope_decls(fn.scope, fn.span) + prologue + self.stmts(fn.body)
        self.depth -= 1
        arguments = ast.arguments(posonlyargs=[], args=args, vararg=None, kwonlyargs=[], kw_defaults=[],
                                  kwarg=None, defaults=defaults)
        returns = self.type_expr(fn.ret) if fn.ret is not None else None
        node = ast.FunctionDef(name=name, args=arguments, body=body or [self.mk(ast.Pass, fn.span)],
                               decorator_list=[], returns=returns, type_comment=None)
        if _HAS_TYPE_PARAMS:
            node.type_params = []
        return self.at(node, fn.span)

    def init_def(self, cls: ClassDecl) -> Optional[ast.FunctionDef]:
        if not cls.fields:
            return None
        span = cls.name_span
        self.depth += 1
        args = [self.mk(ast.arg, span, arg="self", annotation=None)]
        body: List[ast.stmt] = []
        if cls.is_model:
            sup = self.call(self.load("super", span), [], span)
            init = self.mk(ast.Attribute, span, value=sup, attr="__init__", ctx=ast.Load())
            body.append(self.mk(ast.Expr, span, value=self.call(init, [], span)))
        for f in cls.fields:
            if f.value is None:
                annotation = self.type_expr(f.type) if f.type is not None else None
                args.append(self.mk(ast.arg, f.name_span, arg=f.name, annotation=annotation))
                body.append(self.mk(ast.Assign, f.span, targets=[self.self_attr(f.name, f.name_span, ast.Store())],
                                    value=self.load(f.name, f.name_span)))
        for f in cls.fields:
            if f.value is None:
                continue
            target = self.self_attr(f.name, f.name_span, ast.Store())
            if f.type is not None:
                body.append(self.mk(ast.AnnAssign, f.span, target=target, annotation=self.type_expr(f.type),
                                    value=self.expr(f.value), simple=0))
            else:
                body.append(self.mk(ast.Assign, f.span, targets=[target], value=self.expr(f.value)))
        self.depth -= 1
        arguments = ast.arguments(posonlyargs=[], args=args, vararg=None, kwonlyargs=[], kw_defaults=[],
                                  kwarg=None, defaults=[])
        node = ast.FunctionDef(name="__init__", args=arguments, body=body, decorator_list=[], returns=None,
                               type_comment=None)
        if _HAS_TYPE_PARAMS:
            node.type_params = []
        return self.at(node, cls.span)

    def type_expr(self, t: TypeRef) -> ast.expr:
        self.need_future = True   # annotations stay strings; never evaluated
        parts = t.name.split(".")
        if any(p in _PY_KEYWORDS for p in parts):
            return self.mk(ast.Constant, t.span, value=t.name + ("?" if t.nullable else ""))
        node: ast.expr = self.load(parts[0], t.span)
        for p in parts[1:]:
            node = self.mk(ast.Attribute, t.span, value=node, attr=p, ctx=ast.Load())
        if t.args:
            args = [self.type_expr(a) for a in t.args]
            index = args[0] if len(args) == 1 else self.mk(ast.Tuple, t.span, elts=args, ctx=ast.Load())
            node = self.mk(ast.Subscript, t.span, value=node, slice=index, ctx=ast.Load())
        if t.nullable:
            node = self.mk(ast.BinOp, t.span, left=node, op=ast.BitOr(),
                           right=self.mk(ast.Constant, t.span, value=None))
        return node

    # ------------------------------------------------------------------ expressions
    def expr(self, node: Node) -> ast.expr:
        return getattr(self, "e_" + type(node).__name__)(node)

    def e_Num(self, n: Num) -> ast.expr:
        return self.mk(ast.Constant, n.span, value=n.value)

    def e_Const(self, n: Const) -> ast.expr:
        return self.mk(ast.Constant, n.span, value=n.value)

    def e_Str(self, n: Str) -> ast.expr:
        if n.is_plain:
            return self.mk(ast.Constant, n.span, value=n.text)
        if any(isinstance(p, Interp) and _contains_str(p.expr) for p in n.parts):
            return self._joined_by_call(n)
        values: List[ast.expr] = []
        for p in n.parts:
            if isinstance(p, str):
                values.append(self.mk(ast.Constant, n.span, value=p))
                continue
            inner = self.expr(p.expr)
            if p.spec is None:
                inner = self.call(self.prelude("show", p.span), [inner], p.span)
                spec = None
            else:
                spec = self.mk(ast.JoinedStr, p.span, values=[self.mk(ast.Constant, p.span, value=p.spec)])
            values.append(self.mk(ast.FormattedValue, p.span, value=inner, conversion=-1, format_spec=spec))
        return self.mk(ast.JoinedStr, n.span, values=values)

    def _joined_by_call(self, n: Str) -> ast.expr:
        # "".join([...]): keeps `upsil build` output valid on Python 3.10/3.11, where
        # an f-string cannot contain a nested string with the same quotes.
        items: List[ast.expr] = []
        for p in n.parts:
            if isinstance(p, str):
                items.append(self.mk(ast.Constant, n.span, value=p))
            elif p.spec is None:
                items.append(self.call(self.prelude("show", p.span), [self.expr(p.expr)], p.span))
            else:
                items.append(self.call(self.prelude("format", p.span),
                                       [self.expr(p.expr), self.mk(ast.Constant, p.span, value=p.spec)], p.span))
        join = self.mk(ast.Attribute, n.span, value=self.mk(ast.Constant, n.span, value=""), attr="join",
                       ctx=ast.Load())
        return self.call(join, [self.mk(ast.List, n.span, elts=items, ctx=ast.Load())], n.span)

    def e_Name(self, n: Name) -> ast.expr:
        sym: Symbol = n.sym
        if sym.kind == "member":
            return self.self_attr(sym.name, n.span)
        if sym.kind == "builtin" and sym.name in PRELUDE_BUILTINS:
            self.prelude_names.add(sym.name)
        return self.load(sym.pyname, n.span)

    def e_ListLit(self, n: ListLit) -> ast.expr:
        return self.mk(ast.List, n.span, elts=[self.expr(i) for i in n.items], ctx=ast.Load())

    def e_DictLit(self, n: DictLit) -> ast.expr:
        return self.mk(ast.Dict, n.span, keys=[self.expr(k) for k, _ in n.items],
                       values=[self.expr(v) for _, v in n.items])

    def e_Unary(self, n: Unary) -> ast.expr:
        op = ast.USub() if n.op == "-" else ast.UAdd()
        return self.mk(ast.UnaryOp, n.span, op=op, operand=self.expr(n.operand))

    def e_Not(self, n: Not) -> ast.expr:
        return self.mk(ast.UnaryOp, n.span, op=ast.Not(), operand=self.expr(n.operand))

    def e_BinOp(self, n: BinOp) -> ast.expr:
        return self.mk(ast.BinOp, n.span, left=self.expr(n.left), op=_BINOPS[n.op](), right=self.expr(n.right))

    def e_BoolOp(self, n: BoolOp) -> ast.expr:
        operands: List[Node] = []

        def collect(x: Node) -> None:
            if isinstance(x, BoolOp) and x.op == n.op:
                collect(x.left)
                collect(x.right)
            else:
                operands.append(x)

        collect(n)
        op = ast.And() if n.op == "and" else ast.Or()
        return self.mk(ast.BoolOp, n.span, op=op, values=[self.expr(x) for x in operands])

    def e_Compare(self, n: Compare) -> ast.expr:
        left, right, op = n.left, n.right, n.op
        if op in ("==", "!=") and (_is_null(left) or _is_null(right)):
            if _is_null(left) and not _is_null(right):
                left, right = right, left
            py_op = ast.Is() if op == "==" else ast.IsNot()
        else:
            py_op = _CMPOPS[op]()
        return self.mk(ast.Compare, n.span, left=self.expr(left), ops=[py_op], comparators=[self.expr(right)])

    def e_Range(self, n: Range) -> ast.expr:
        if getattr(n, "prelude_range", False):
            func = self.prelude("range", n.span)
        else:
            func = self.load("range", n.span)
        end = self.expr(n.end)
        if n.inclusive:
            end = self.mk(ast.BinOp, n.end.span, left=end, op=ast.Add(), right=self.mk(ast.Constant, n.end.span, value=1))
        return self.call(func, [self.expr(n.start), end], n.span)

    def e_Call(self, n: Call) -> ast.expr:
        f = n.func
        if (isinstance(f, Name) and f.sym is not None and f.sym.kind == "builtin" and f.name == "div"
                and len(n.args) == 2 and all(a.name is None for a in n.args)):
            return self.mk(ast.BinOp, n.span, left=self.expr(n.args[0].value), op=ast.FloorDiv(),
                           right=self.expr(n.args[1].value))
        args = [self.expr(a.value) for a in n.args if a.name is None]
        keywords = [self.mk(ast.keyword, a.span, arg=a.name, value=self.expr(a.value))
                    for a in n.args if a.name is not None]
        return self.call(self.expr(f), args, n.span, keywords)

    def subscript(self, n: Index) -> ast.expr:
        items = [self.slice_or_expr(i) for i in n.items]
        if len(items) == 1:
            return items[0]
        return self.mk(ast.Tuple, n.items[0].span.to(n.items[-1].span), elts=items, ctx=ast.Load())

    def slice_or_expr(self, item: Node) -> ast.expr:
        if isinstance(item, Slice):
            return self.mk(ast.Slice, item.span,
                           lower=self.expr(item.lo) if item.lo is not None else None,
                           upper=self.expr(item.hi) if item.hi is not None else None,
                           step=self.expr(item.step) if item.step is not None else None)
        return self.expr(item)

    def e_Index(self, n: Index) -> ast.expr:
        return self.mk(ast.Subscript, n.span, value=self.expr(n.obj), slice=self.subscript(n), ctx=ast.Load())

    def e_Attr(self, n: Attr) -> ast.expr:
        return self.mk(ast.Attribute, n.span, value=self.expr(n.obj), attr=n.name, ctx=ast.Load())

    def e_Prompt(self, n: Prompt) -> ast.expr:
        keywords = []
        if n.system is not None:
            keywords.append(self.mk(ast.keyword, n.system.span, arg="system", value=self.expr(n.system)))
        if n.decision is not None:
            args = [self.expr(n.model), self.expr(n.text), self.mk(ast.Constant, n.span, value=n.decision)]
            if n.options is not None:
                args.append(self.expr(n.options))
            return self.call(self.prelude("decide", n.span), args, n.span, keywords)
        if n.as_json:
            keywords.append(self.mk(ast.keyword, n.span, arg="json", value=self.mk(ast.Constant, n.span, value=True)))
        if n.schema is not None:
            keywords.append(self.mk(ast.keyword, n.schema.span, arg="schema", value=self.expr(n.schema)))
        return self.call(self.prelude("prompt", n.span), [self.expr(n.model), self.expr(n.text)], n.span, keywords)

    def e_TupleLit(self, n: TupleLit) -> ast.expr:
        return self.mk(ast.Tuple, n.span, elts=[self.expr(i) for i in n.items], ctx=ast.Load())

    def e_IfExpr(self, n: IfExpr) -> ast.expr:
        return self.mk(ast.IfExp, n.span, test=self.expr(n.cond), body=self.expr(n.then), orelse=self.expr(n.orelse))

    def e_Lambda(self, n: Lambda) -> ast.expr:
        args = [self.mk(ast.arg, p.span, arg=p.sym.pyname, annotation=None) for p in n.params]
        arguments = ast.arguments(posonlyargs=[], args=args, vararg=None, kwonlyargs=[], kw_defaults=[],
                                  kwarg=None, defaults=[])
        return self.mk(ast.Lambda, n.span, args=arguments, body=self.expr(n.body))

    def e_Comprehension(self, n: Comprehension) -> ast.expr:
        generators = []
        for clause in n.fors:
            names = [self.mk(ast.Name, span, id=sym.pyname, ctx=ast.Store())
                     for sym, span in zip(clause.syms, clause.name_spans)]
            if len(names) == 1:
                target = names[0]
            else:
                target = self.mk(ast.Tuple, clause.name_spans[0].to(clause.name_spans[-1]), elts=names,
                                 ctx=ast.Store())
            generators.append(ast.comprehension(target=target, iter=self.expr(clause.iter),
                                                ifs=[self.expr(c) for c in clause.conds], is_async=0))
        if n.kind == "list":
            return self.mk(ast.ListComp, n.span, elt=self.expr(n.elt), generators=generators)
        if n.kind == "dict":
            return self.mk(ast.DictComp, n.span, key=self.expr(n.elt), value=self.expr(n.value),
                           generators=generators)
        return self.mk(ast.GeneratorExp, n.span, elt=self.expr(n.elt), generators=generators)


def _is_null(node: Node) -> bool:
    return isinstance(node, Const) and node.value is None


def generate(result: CheckResult, source: str, *, repl: bool = False) -> ast.Module:
    return Codegen(result, source, repl=repl).module(result.module)
