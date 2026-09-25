# SPDX-License-Identifier: Apache-2.0
"""UpsiL parser: tokens -> syntax tree (``upsil.nodes``).

Statements are parsed by recursive descent, expressions by precedence
climbing. Binding powers, weakest first:

    or                                  1  left
    and                                 2  left
    not x                               3  prefix
    == != < <= > >= in  not in          4  non-associative
    ..  ..=                             5  non-associative
    + -                                 6  left
    * / % @                             7  left
    -x +x                               8  prefix
    **                                  9  right; -2 ** 2 == -(2 ** 2)
    f(x)  a[i]  a[i:j]  a.b             10 postfix

``[m] => text`` is a prefix form whose text is a whole expression.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .errors import CompileError, Diagnostic
from .keywords import PYTHON_ONLY_KEYWORDS
from .lexer import Token, tokenize
from .nodes import (Arg, Assign, Attr, AugAssign, BinOp, BoolOp, Break, Call, ClassDecl, Compare,
                    Const, Continue, DictLit, ExprStmt, For, FunDecl, If, Import, Index, Interp,
                    ListLit, Module, Name, Node, Not, Num, Param, Prompt, PyImport, Range,
                    ResourceDecl, Return, Slice, Span, Str, TypeRef, Unary, VarDecl, While)

_PY_KEYWORDS = frozenset(PYTHON_ONLY_KEYWORDS)
# UpsiL keywords that are also Python keywords cannot name an argument or attribute
_KW_NOT_ALLOWED_AS_NAME = frozenset({
    "if", "else", "while", "for", "return", "break", "continue", "class", "import", "as",
    "and", "or", "not", "in",
})

_COMPARISONS = ("==", "!=", "<", "<=", ">", ">=")
_BIN_POWER = {"+": 6, "-": 6, "*": 7, "/": 7, "%": 7, "@": 7}
_AUG_OPS = ("+=", "-=", "*=", "/=", "%=")


class Parser:
    def __init__(self, tokens: List[Token], source: str, filename: str):
        self.toks = tokens
        self.i = 0
        self.source = source
        self.filename = filename

    # ------------------------------------------------------------------ cursor
    def peek(self, k: int = 0) -> Token:
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else self.toks[-1]

    def advance(self) -> Token:
        tok = self.toks[self.i]
        if tok.kind != "EOF":
            self.i += 1
        return tok

    def at(self, kind: str) -> bool:
        return self.peek().kind == kind

    def at_op(self, *ops: str) -> bool:
        t = self.peek()
        return t.kind == "OP" and t.value in ops

    def at_kw(self, *kws: str) -> bool:
        t = self.peek()
        return t.kind == "KW" and t.value in kws

    def fail(self, span: Span, en: str, ru: str, incomplete: bool = False) -> None:
        raise CompileError([Diagnostic(span, en, ru, incomplete=incomplete)], self.filename, self.source)

    def unexpected(self, tok: Token, expected_en: str, expected_ru: str) -> None:
        u_en, u_ru = tok.unexpected()
        self.fail(tok.span, f"{u_en} — expected {expected_en}", f"{u_ru} — ожидалось {expected_ru}",
                  incomplete=tok.kind == "EOF")

    def expect_op(self, op: str) -> Token:
        if not self.at_op(op):
            self.unexpected(self.peek(), f"'{op}'", f"'{op}'")
        return self.advance()

    def expect_kw(self, kw: str) -> Token:
        if not self.at_kw(kw):
            self.unexpected(self.peek(), f"'{kw}'", f"'{kw}'")
        return self.advance()

    def expect_name(self, what_en: str, what_ru: str) -> Token:
        t = self.peek()
        if t.kind != "NAME":
            if t.kind == "KW":
                self.fail(t.span, f"'{t.value}' is a keyword — expected {what_en}",
                          f"'{t.value}' — ключевое слово, а ожидалось {what_ru}")
            self.unexpected(t, what_en, what_ru)
        return self.advance()

    def skip_newlines(self) -> None:
        while self.at("NEWLINE"):
            self.advance()

    def skip_separators(self) -> None:
        while self.at("NEWLINE") or self.at_op(";"):
            self.advance()

    # ------------------------------------------------------------------ module
    def parse_module(self) -> Module:
        body: List[Node] = []
        self.skip_separators()
        while not self.at("EOF"):
            body.append(self.statement())
            self.skip_separators()
        eof = self.peek()
        return Module(Span(1, 1, eof.span.line, eof.span.col), body)

    # ------------------------------------------------------------------ statements
    def statement(self) -> Node:
        t = self.peek()
        if t.kind == "KW":
            v = t.value
            if v in ("val", "var"):
                return self.end_simple(self.var_decl())
            if v == "fun":
                return self.fun_decl()
            if v == "class":
                return self.class_decl(is_model=False)
            if v == "if":
                return self.if_stmt()
            if v == "while":
                return self.while_stmt()
            if v == "for":
                return self.for_stmt()
            if v == "return":
                return self.end_simple(self.return_stmt())
            if v == "break":
                return self.end_simple(Break(self.advance().span))
            if v == "continue":
                return self.end_simple(Continue(self.advance().span))
            if v == "import":
                return self.end_simple(self.import_stmt())
            if v == "else":
                self.fail(t.span, "'else' without 'if'", "'else' без 'if'")
        elif t.kind == "NAME":
            nxt = self.peek(1)
            if t.value in ("llm", "vector_store") and nxt.kind == "NAME":
                return self.end_simple(self.resource_decl())
            if t.value == "model" and nxt.kind == "NAME":
                return self.class_decl(is_model=True)
            if t.value == "graph" and nxt.kind == "NAME" and self.peek(2).kind == "OP" and self.peek(2).value == "(":
                self.fail(t.span, "graph methods are only allowed inside a model",
                          "методы graph допустимы только внутри model")
        return self.end_simple(self.simple_statement())

    def end_simple(self, node: Node) -> Node:
        t = self.peek()
        if t.kind == "NEWLINE" or (t.kind == "OP" and t.value == ";"):
            self.advance()
            return node
        if t.kind == "EOF" or (t.kind == "OP" and t.value == "}"):
            return node
        u_en, u_ru = t.unexpected()
        self.fail(t.span, f"{u_en} — expected the end of the statement (a new line or ';')",
                  f"{u_ru} — ожидалось окончание инструкции (перевод строки или ';')")
        return node

    def block(self) -> Tuple[List[Node], Token]:
        self.skip_newlines()
        opening = self.peek()
        if not self.at_op("{"):
            self.unexpected(opening, "'{'", "'{'")
        self.advance()
        body: List[Node] = []
        self.skip_separators()
        while not self.at_op("}"):
            if self.at("EOF"):
                self.fail(opening.span, "'{' is never closed", "скобка '{' не закрыта", incomplete=True)
            body.append(self.statement())
            self.skip_separators()
        return body, self.advance()

    def var_decl(self, in_class: bool = False) -> VarDecl:
        kw = self.advance()
        name = self.expect_name("a variable name", "имя переменной")
        typ = None
        if self.at_op(":"):
            self.advance()
            typ = self.type_ref()
        value = None
        if self.at_op("="):
            self.advance()
            value = self.expression()
        elif kw.value == "val" and not in_class:
            self.fail(name.span, f"val '{name.value}' needs a value: val {name.value} = ...",
                      f"для val '{name.value}' нужно значение: val {name.value} = ...")
        end = value.span if value is not None else (typ.span if typ is not None else name.span)
        return VarDecl(kw.span.to(end), kw.value == "var", name.value, name.span, typ, value)

    def type_ref(self) -> TypeRef:
        first = self.expect_name("a type", "тип")
        name, end = first.value, first.span
        while self.at_op("."):
            self.advance()
            part = self.expect_name("a type", "тип")
            name += "." + part.value
            end = part.span
        args: List[TypeRef] = []
        if self.at_op("["):
            self.advance()
            args.append(self.type_ref())
            while self.at_op(","):
                self.advance()
                if self.at_op("]"):
                    break
                args.append(self.type_ref())
            end = self.expect_op("]").span
        nullable = False
        if self.at_op("?"):
            end = self.advance().span
            nullable = True
        return TypeRef(first.span.to(end), name, args, nullable)

    def resource_decl(self) -> ResourceDecl:
        kind = self.advance()
        name = self.expect_name("a name", "имя")
        value = None
        if self.at_op("="):
            self.advance()
            value = self.expression()
        end = value.span if value is not None else name.span
        return ResourceDecl(kind.span.to(end), kind.value, name.value, name.span, value)

    def fun_decl(self, kind: str = "fun") -> FunDecl:
        kw = self.advance()
        name = self.expect_name("a function name", "имя функции")
        self.expect_op("(")
        params: List[Param] = []
        while not self.at_op(")"):
            p = self.expect_name("a parameter name", "имя параметра")
            ptype = None
            default = None
            end = p.span
            if self.at_op(":"):
                self.advance()
                ptype = self.type_ref()
                end = ptype.span
            if self.at_op("="):
                self.advance()
                default = self.expression()
                end = default.span
            params.append(Param(p.span.to(end), p.value, ptype, default))
            if self.at_op(","):
                self.advance()
                continue
            if not self.at_op(")"):
                self.unexpected(self.peek(), "',' or ')'", "',' или ')'")
        self.expect_op(")")
        ret = None
        if self.at_op("->"):
            self.advance()
            ret = self.type_ref()
        body, close = self.block()
        return FunDecl(kw.span.to(close.span), name.value, name.span, params, ret, body, kind)

    def class_decl(self, is_model: bool) -> ClassDecl:
        kw = self.advance()
        if is_model:
            name = self.expect_name("a model name", "имя модели")
        else:
            name = self.expect_name("a class name", "имя класса")
        self.skip_newlines()
        self.expect_op("{")
        fields: List[VarDecl] = []
        methods: List[FunDecl] = []
        self.skip_separators()
        while not self.at_op("}"):
            t = self.peek()
            if t.kind == "KW" and t.value in ("val", "var"):
                fields.append(self.end_simple(self.var_decl(in_class=True)))
            elif t.kind == "KW" and t.value == "fun":
                methods.append(self.fun_decl())
            elif t.kind == "NAME" and t.value == "graph" and self.peek(1).kind == "NAME":
                if not is_model:
                    self.fail(t.span, "graph methods are only allowed inside a model",
                              "методы graph допустимы только внутри model")
                methods.append(self.fun_decl(kind="graph"))
            else:
                if is_model:
                    self.fail(t.span, "a model body may contain only fields (val/var) and methods (fun/graph)",
                              "в теле model допустимы только поля (val/var) и методы (fun/graph)")
                self.fail(t.span, "a class body may contain only fields (val/var) and methods (fun)",
                          "в теле класса допустимы только поля (val/var) и методы (fun)")
            self.skip_separators()
        close = self.advance()
        return ClassDecl(kw.span.to(close.span), name.value, name.span, fields, methods, is_model)

    def if_stmt(self) -> If:
        kw = self.advance()
        cond = self.expression()
        body, close = self.block()
        orelse: List[Node] = []
        end = close.span
        j = self.i
        while self.toks[j].kind == "NEWLINE":
            j += 1
        if self.toks[j].kind == "KW" and self.toks[j].value == "else":
            self.i = j
            self.advance()
            if self.at_kw("if"):
                nested = self.if_stmt()
                orelse = [nested]
                end = nested.span
            else:
                orelse, close2 = self.block()
                end = close2.span
        return If(kw.span.to(end), cond, body, orelse)

    def while_stmt(self) -> While:
        kw = self.advance()
        cond = self.expression()
        body, close = self.block()
        return While(kw.span.to(close.span), cond, body)

    def _matching_paren(self, i: int) -> int:
        depth = 0
        for j in range(i, len(self.toks)):
            t = self.toks[j]
            if t.kind == "OP" and t.value == "(":
                depth += 1
            elif t.kind == "OP" and t.value == ")":
                depth -= 1
                if depth == 0:
                    return j
        return len(self.toks) - 1

    def _for_target(self) -> Tuple[List[str], List[Span]]:
        names: List[Token] = []
        if self.at_op("("):
            self.advance()
            names.append(self.expect_name("a loop variable", "переменная цикла"))
            while self.at_op(","):
                self.advance()
                names.append(self.expect_name("a loop variable", "переменная цикла"))
            self.expect_op(")")
        else:
            names.append(self.expect_name("a loop variable", "переменная цикла"))
            while self.at_op(","):
                self.advance()
                names.append(self.expect_name("a loop variable", "переменная цикла"))
        return [t.value for t in names], [t.span for t in names]

    def for_stmt(self) -> For:
        kw = self.advance()
        if self.at_op("("):
            close = self._matching_paren(self.i)
            after = self.toks[close + 1] if close + 1 < len(self.toks) else self.toks[-1]
            if after.kind == "KW" and after.value == "in":
                # for (a, b) in pairs { ... }
                names, spans = self._for_target()
                self.expect_kw("in")
                iterable = self.expression()
            else:
                # for (x in xs) { ... }
                self.advance()
                names, spans = self._for_target()
                self.expect_kw("in")
                iterable = self.expression()
                self.expect_op(")")
        else:
            names, spans = self._for_target()
            self.expect_kw("in")
            iterable = self.expression()
        body, close_tok = self.block()
        return For(kw.span.to(close_tok.span), names, spans, iterable, body)

    def return_stmt(self) -> Return:
        kw = self.advance()
        t = self.peek()
        if t.kind in ("NEWLINE", "EOF") or (t.kind == "OP" and t.value in (";", "}")):
            return Return(kw.span, None)
        value = self.expression()
        return Return(kw.span.to(value.span), value)

    def import_stmt(self) -> Node:
        kw = self.advance()
        t = self.peek()
        if t.kind == "NAME" and t.value == "py" and self.peek(1).kind == "STRING":
            self.advance()
            s = self.advance()
            if any(not isinstance(p, str) for p in s.value):
                self.fail(s.span, "a module name cannot contain { }", "в имени модуля не может быть { }")
            module = "".join(s.value)
            alias = None
            end = s.span
            if self.at_kw("as"):
                self.advance()
                a = self.expect_name("a name after 'as'", "имя после 'as'")
                alias, end = a.value, a.span
            return PyImport(kw.span.to(end), module, alias)
        first = self.expect_name("a module name", "имя модуля")
        path = [first.value]
        end = first.span
        while self.at_op("."):
            self.advance()
            part = self.expect_name("a module name", "имя модуля")
            path.append(part.value)
            end = part.span
        alias = None
        if self.at_kw("as"):
            self.advance()
            a = self.expect_name("a name after 'as'", "имя после 'as'")
            alias, end = a.value, a.span
        return Import(kw.span.to(end), path, alias)

    def simple_statement(self) -> Node:
        expr = self.expression()
        if self.at_op("="):
            self.advance()
            self._check_target(expr)
            value = self.expression()
            return Assign(expr.span.to(value.span), expr, value)
        if self.at_op(*_AUG_OPS):
            op = self.advance().value[0]
            self._check_target(expr)
            value = self.expression()
            return AugAssign(expr.span.to(value.span), expr, op, value)
        return ExprStmt(expr.span, expr)

    def _check_target(self, expr: Node) -> None:
        if not isinstance(expr, (Name, Attr, Index)):
            self.fail(expr.span, "cannot assign to this expression", "этому выражению нельзя присвоить значение")

    # ------------------------------------------------------------------ expressions
    def expression(self, min_bp: int = 0) -> Node:
        left = self.prefix()
        while True:
            t = self.peek()
            info = self._infix(t)
            if info is None:
                break
            op, lbp, kind = info
            if lbp < min_bp:
                break
            if kind == "cmp" and isinstance(left, Compare) and not left.parens:
                self.fail(t.span, "comparisons cannot be chained: write a < b and b < c",
                          "сравнения нельзя записывать цепочкой: пишите a < b and b < c")
            if kind == "range" and isinstance(left, Range) and not left.parens:
                self.fail(t.span, "ranges cannot be chained", "диапазоны нельзя записывать цепочкой")
            self.advance()
            if op == "not in":
                self.advance()
            right = self.expression(8 if kind == "pow" else lbp + 1)
            span = left.span.to(right.span)
            if kind == "bool":
                left = BoolOp(span, op, left, right)
            elif kind == "cmp":
                left = Compare(span, op, left, right)
            elif kind == "range":
                left = Range(span, left, right, op == "..=")
            else:
                left = BinOp(span, op, left, right)
        return left

    def _infix(self, t: Token) -> Optional[Tuple[str, int, str]]:
        if t.kind == "OP":
            v = t.value
            if v in _BIN_POWER:
                return v, _BIN_POWER[v], "bin"
            if v == "**":
                return v, 9, "pow"
            if v in _COMPARISONS:
                return v, 4, "cmp"
            if v in ("..", "..="):
                return v, 5, "range"
            return None
        if t.kind == "KW":
            v = t.value
            if v == "or":
                return v, 1, "bool"
            if v == "and":
                return v, 2, "bool"
            if v == "in":
                return v, 4, "cmp"
            if v == "not":
                nxt = self.peek(1)
                if nxt.kind == "KW" and nxt.value == "in":
                    return "not in", 4, "cmp"
        return None

    def prefix(self) -> Node:
        t = self.peek()
        if t.kind == "OP" and t.value in ("-", "+"):
            self.advance()
            operand = self.expression(8)
            return Unary(t.span.to(operand.span), t.value, operand)
        if t.kind == "KW" and t.value == "not":
            self.advance()
            operand = self.expression(3)
            return Not(t.span.to(operand.span), operand)
        return self.postfix(self.primary())

    def postfix(self, node: Node) -> Node:
        while True:
            if self.at_op("("):
                node = self.call(node)
            elif self.at_op("["):
                node = self.index(node)
            elif self.at_op("."):
                self.advance()
                t = self.peek()
                if t.kind == "NAME" or (t.kind == "KW" and t.value not in _KW_NOT_ALLOWED_AS_NAME):
                    if t.value in _PY_KEYWORDS:
                        self.fail(t.span, f"'{t.value}' cannot be an attribute name (it is a Python keyword)",
                                  f"'{t.value}' не может быть именем атрибута (это ключевое слово Python)")
                    self.advance()
                    node = Attr(node.span.to(t.span), node, t.value, t.span)
                else:
                    self.unexpected(t, "an attribute name", "имя атрибута")
            else:
                return node

    def primary(self) -> Node:
        t = self.peek()
        k = t.kind
        if k in ("INT", "FLOAT"):
            self.advance()
            return Num(t.span, t.value)
        if k == "STRING":
            self.advance()
            return self.string(t)
        if k == "NAME":
            self.advance()
            return Name(t.span, t.value)
        if k == "KW":
            if t.value == "true":
                self.advance()
                return Const(t.span, True)
            if t.value == "false":
                self.advance()
                return Const(t.span, False)
            if t.value == "null":
                self.advance()
                return Const(t.span, None)
        if k == "OP":
            if t.value == "(":
                self.advance()
                if self.at_op(")"):
                    self.fail(self.peek().span, "empty parentheses — expected an expression",
                              "пустые скобки — ожидалось выражение")
                expr = self.expression()
                self.expect_op(")")
                expr.parens = True
                return expr
            if t.value == "[":
                return self.list_or_prompt()
            if t.value == "{":
                return self.dict_lit()
        self.unexpected(t, "an expression", "выражение")
        raise AssertionError("unreachable")

    def string(self, tok: Token) -> Str:
        parts: list = []
        for p in tok.value:
            if isinstance(p, str):
                parts.append(p)
                continue
            sub = Parser(p.tokens, self.source, self.filename)
            expr = sub.expression()
            if not sub.at("EOF"):
                sub.unexpected(sub.peek(), "'}'", "'}'")
            parts.append(Interp(p.span, expr, p.spec))
        return Str(tok.span, parts)

    def list_or_prompt(self) -> Node:
        opening = self.advance()
        items: List[Node] = []
        options: List[Tuple[Token, Node]] = []
        while not self.at_op("]"):
            t = self.peek()
            nxt = self.peek(1)
            if t.kind == "NAME" and nxt.kind == "OP" and nxt.value == ":":
                self.advance()
                self.advance()
                options.append((t, self.expression()))
            else:
                if options:
                    self.fail(t.span, "the model comes first: [m, system: \"...\"]",
                              "модель указывается первой: [m, system: \"...\"]")
                items.append(self.expression())
            if self.at_op(","):
                self.advance()
                continue
            if not self.at_op("]"):
                self.unexpected(self.peek(), "',' or ']'", "',' или ']'")
        close = self.advance()
        if self.at_op("=>"):
            self.advance()
            if len(items) != 1:
                self.fail(opening.span.to(close.span), "a prompt takes exactly one model: [m] => \"...\"",
                          "в промпте указывается ровно одна модель: [m] => \"...\"")
            system = None
            for name_tok, value in options:
                if name_tok.value != "system":
                    self.fail(name_tok.span, f"unknown prompt option '{name_tok.value}' (supported: system)",
                              f"неизвестный параметр промпта '{name_tok.value}' (поддерживается только system)")
                if system is not None:
                    self.fail(name_tok.span, "'system' is given twice", "'system' указан дважды")
                system = value
            text = self.expression()
            end = text.span
            as_json = False
            if self.at_op("->"):
                self.advance()
                fmt = self.peek()
                if fmt.kind != "NAME" or fmt.value != "json":
                    self.fail(fmt.span, "only '-> json' is supported after a prompt",
                              "после промпта поддерживается только '-> json'")
                self.advance()
                as_json = True
                end = fmt.span
            return Prompt(opening.span.to(end), items[0], text, system, as_json)
        if options:
            self.fail(options[0][0].span,
                      "'name: value' is only allowed in a prompt: [m, system: \"...\"] => \"...\"",
                      "'имя: значение' допустимо только в промпте: [m, system: \"...\"] => \"...\"")
        return ListLit(opening.span.to(close.span), items)

    def dict_lit(self) -> DictLit:
        opening = self.advance()
        items: List[Tuple[Node, Node]] = []
        self.skip_newlines()
        while not self.at_op("}"):
            key = self.expression()
            self.skip_newlines()
            self.expect_op(":")
            self.skip_newlines()
            value = self.expression()
            items.append((key, value))
            self.skip_newlines()
            if self.at_op(","):
                self.advance()
                self.skip_newlines()
                continue
            if not self.at_op("}"):
                self.unexpected(self.peek(), "',' or '}'", "',' или '}'")
        close = self.advance()
        return DictLit(opening.span.to(close.span), items)

    def call(self, func: Node) -> Call:
        self.advance()
        args: List[Arg] = []
        named = set()
        while not self.at_op(")"):
            t = self.peek()
            nxt = self.peek(1)
            is_named = (nxt.kind == "OP" and nxt.value == "="
                        and (t.kind == "NAME" or (t.kind == "KW" and t.value not in _KW_NOT_ALLOWED_AS_NAME)))
            if is_named:
                if t.value in _PY_KEYWORDS:
                    self.fail(t.span, f"'{t.value}' cannot be an argument name (it is a Python keyword)",
                              f"'{t.value}' не может быть именем аргумента (это ключевое слово Python)")
                if t.value in named:
                    self.fail(t.span, f"argument '{t.value}' is given twice", f"аргумент '{t.value}' передан дважды")
                named.add(t.value)
                self.advance()
                self.advance()
                value = self.expression()
                args.append(Arg(t.span.to(value.span), t.value, value))
            else:
                value = self.expression()
                if named:
                    self.fail(value.span, "a positional argument cannot follow a named one",
                              "позиционный аргумент не может идти после именованного")
                args.append(Arg(value.span, None, value))
            if self.at_op(","):
                self.advance()
                continue
            if not self.at_op(")"):
                self.unexpected(self.peek(), "',' or ')'", "',' или ')'")
        close = self.advance()
        return Call(func.span.to(close.span), func, args)

    def index(self, obj: Node) -> Index:
        self.advance()
        items: List[Node] = [self.subscript()]
        while self.at_op(","):
            self.advance()
            if self.at_op("]"):
                break
            items.append(self.subscript())
        close = self.expect_op("]")
        return Index(obj.span.to(close.span), obj, items)

    def subscript(self) -> Node:
        start = self.peek().span
        lo = hi = step = None
        if not self.at_op(":"):
            lo = self.expression()
            if not self.at_op(":"):
                return lo
        end = self.advance().span
        if not self.at_op(":", "]", ","):
            hi = self.expression()
            end = hi.span
        if self.at_op(":"):
            end = self.advance().span
            if not self.at_op("]", ","):
                step = self.expression()
                end = step.span
        return Slice(start.to(end), lo, hi, step)


def parse(source: str, filename: str = "<input>") -> Module:
    tokens = tokenize(source, filename)
    from .lexer import normalize_source
    return Parser(tokens, normalize_source(source), filename).parse_module()


def parse_expression(source: str, filename: str = "<input>") -> Node:
    """Parse one expression (used by tests and the REPL)."""
    from .lexer import normalize_source
    tokens = tokenize(source, filename)
    p = Parser(tokens, normalize_source(source), filename)
    p.skip_newlines()
    expr = p.expression()
    p.skip_separators()
    if not p.at("EOF"):
        p.unexpected(p.peek(), "the end of the expression", "конец выражения")
    return expr
