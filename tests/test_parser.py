# SPDX-License-Identifier: Apache-2.0
import unittest

from support import UpsilTestCase, lang

from upsil import nodes as n
from upsil.errors import CompileError
from upsil.parser import parse, parse_expression


def sx(node) -> str:
    """A compact s-expression, to compare trees in tests."""
    if isinstance(node, n.Num):
        return repr(node.value)
    if isinstance(node, n.Name):
        return node.name
    if isinstance(node, n.Const):
        return {True: "true", False: "false", None: "null"}[node.value]
    if isinstance(node, n.Str):
        return " ".join(repr(p) if isinstance(p, str) else "{" + sx(p.expr) + (":" + p.spec if p.spec else "") + "}"
                        for p in node.parts) or '""'
    if isinstance(node, (n.BinOp, n.BoolOp, n.Compare)):
        return f"({node.op} {sx(node.left)} {sx(node.right)})"
    if isinstance(node, n.Unary):
        return f"({'neg' if node.op == '-' else 'pos'} {sx(node.operand)})"
    if isinstance(node, n.Not):
        return f"(not {sx(node.operand)})"
    if isinstance(node, n.Range):
        return f"({'..=' if node.inclusive else '..'} {sx(node.start)} {sx(node.end)})"
    if isinstance(node, n.Call):
        args = [(a.name + "=" if a.name else "") + sx(a.value) for a in node.args]
        return "(call " + " ".join([sx(node.func)] + args) + ")"
    if isinstance(node, n.Index):
        return "(index " + " ".join([sx(node.obj)] + [sx(i) for i in node.items]) + ")"
    if isinstance(node, n.Slice):
        return "(slice " + " ".join(sx(p) if p is not None else "_" for p in (node.lo, node.hi, node.step)) + ")"
    if isinstance(node, n.Attr):
        return f"(. {sx(node.obj)} {node.name})"
    if isinstance(node, n.ListLit):
        return "[" + " ".join(sx(i) for i in node.items) + "]"
    if isinstance(node, n.DictLit):
        return "{" + ", ".join(f"{sx(k)}: {sx(v)}" for k, v in node.items) + "}"
    if isinstance(node, n.Prompt):
        extra = (f" system={sx(node.system)}" if node.system else "") + (" json" if node.as_json else "")
        return f"(prompt {sx(node.model)} {sx(node.text)}{extra})"
    raise AssertionError(type(node))


def stmt_kinds(src):
    return [type(s).__name__ for s in parse(src).body]


def parse_error(src):
    with lang("en"):
        try:
            parse(src)
        except CompileError as e:
            d = e.diagnostics[0]
            return d.message, d.span.line, d.span.col
    raise AssertionError("no error")


class PrecedenceTest(UpsilTestCase):
    TABLE = [
        ("1 + 2 * 3", "(+ 1 (* 2 3))"),
        ("(1 + 2) * 3", "(* (+ 1 2) 3)"),
        ("1 - 2 - 3", "(- (- 1 2) 3)"),
        ("a * b % c / d", "(/ (% (* a b) c) d)"),
        ("a @ b + c", "(+ (@ a b) c)"),
        ("2 ** 3 ** 2", "(** 2 (** 3 2))"),
        ("-2 ** 2", "(neg (** 2 2))"),
        ("2 ** -1", "(** 2 (neg 1))"),
        ("-a * b", "(* (neg a) b)"),
        ("-f(x)", "(neg (call f x))"),
        ("a or b and c", "(or a (and b c))"),
        ("a and b or c and d", "(or (and a b) (and c d))"),
        ("not a == b", "(not (== a b))"),
        ("not a and b", "(and (not a) b)"),
        ("a == b and c != d", "(and (== a b) (!= c d))"),
        ("a + b < c * d or e", "(or (< (+ a b) (* c d)) e)"),
        ("x in 0..n + 1", "(in x (.. 0 (+ n 1)))"),
        ("x not in xs", "(not in x xs)"),
        ("0..=n - 1", "(..= 0 (- n 1))"),
        ("f(x)[0].y", "(. (index (call f x) 0) y)"),
        ("a.b(c).d[1:2]", "(index (. (call (. a b) c) d) (slice 1 2 _))"),
        ("xs[:]", "(index xs (slice _ _ _))"),
        ("xs[::2]", "(index xs (slice _ _ 2))"),
        ("t[0, :]", "(index t 0 (slice _ _ _))"),
        ("f(1, k = 2)", "(call f 1 k=2)"),
        ("f(val = 1)", "(call f val=1)"),
        ('{"a": 1, "b": [2, 3]}', "{'a': 1, 'b': [2 3]}"),
        ("[]", "[]"),
        ("{}", "{}"),
        ("true and null", "(and true null)"),
        ('"Hi {name}!"', "'Hi ' {name} '!'"),
        ('"{a + b * 2:.1f}"', "{(+ a (* b 2)):.1f}"),
        ('[m] => "Summarize {doc}"', "(prompt m 'Summarize ' {doc})"),
        ('[m, system: "terse"] => q -> json', "(prompt m q system='terse' json)"),
        ('[m] => "a" + b', "(prompt m (+ 'a' b))"),
    ]

    def test_table(self):
        for src, expected in self.TABLE:
            with self.subTest(src=src):
                self.assertEqual(sx(parse_expression(src)), expected)

    def test_not_inside_and_or(self):
        self.assertEqual(sx(parse_expression("not a or not b and c")), "(or (not a) (and (not b) c))")
        self.assertEqual(sx(parse_expression("a == (not b)")), "(== a (not b))")

    def test_parenthesized_comparisons_may_nest(self):
        self.assertEqual(sx(parse_expression("(a < b) == c")), "(== (< a b) c)")

    def test_positions(self):
        e = parse_expression("  foo + bar")
        self.assertEqual((e.span.line, e.span.col, e.span.end_col), (1, 3, 12))
        self.assertEqual((e.right.span.col, e.right.span.end_col), (9, 12))


class StatementsTest(UpsilTestCase):
    def test_newline_ends_statements(self):
        body = parse("val x = 5\n-3\nprint(x)").body
        self.assertEqual([type(s).__name__ for s in body], ["VarDecl", "ExprStmt", "ExprStmt"])
        self.assertEqual(sx(body[0].value), "5")
        self.assertEqual(sx(body[1].expr), "(neg 3)")

    def test_continuations(self):
        self.assertEqual(sx(parse("val y = 1 +\n  2").body[0].value), "(+ 1 2)")
        self.assertEqual(sx(parse("foo(1,\n  2)").body[0].expr), "(call foo 1 2)")
        self.assertEqual(sx(parse("val xs = [\n  1,\n  2,\n]").body[0].value), "[1 2]")
        self.assertEqual(sx(parse('val d = {\n  "a": 1,\n  "b": 2\n}').body[0].value), "{'a': 1, 'b': 2}")
        self.assertEqual(sx(parse("s\n  .strip()\n  .lower()").body[0].expr), "(call (. (call (. s strip)) lower))")
        self.assertEqual(sx(parse("val ok = a and\n  b").body[0].value), "(and a b)")

    def test_semicolons(self):
        self.assertEqual(stmt_kinds("a; b;; c"), ["ExprStmt"] * 3)

    def test_statement_after_closing_brace_on_the_same_line(self):
        body = parse("fun main() { for (i in 0..3) { print(i) }  print(1) }").body
        self.assertEqual([type(s).__name__ for s in body[0].body], ["For", "ExprStmt"])

    def test_else_on_next_line_and_allman_braces(self):
        s = parse("if a\n{\n  x()\n}\nelse if b {\n}\nelse\n{\n  y()\n}").body[0]
        self.assertIsInstance(s, n.If)
        self.assertIsInstance(s.orelse[0], n.If)
        self.assertEqual(len(s.orelse[0].orelse), 1)

    def test_brace_on_the_next_line(self):
        src = ("fun f()\n{\n  while x\n  {\n  }\n  for (i in xs)\n  {\n  }\n}\n"
               "class C\n{\n  val a = 1\n}\nmodel M\n{\n  graph forward(x)\n  {\n    return x\n  }\n}")
        self.assertEqual(stmt_kinds(src), ["FunDecl", "ClassDecl", "ClassDecl"])

    def test_bare_return_at_end_of_line(self):
        f = parse("fun f() {\n  return\n  x\n}").body[0]
        self.assertIsNone(f.body[0].value)
        self.assertIsInstance(f.body[1], n.ExprStmt)

    def test_for_forms(self):
        for src, names, it in [("for (i in 0..3) {}", ["i"], "(.. 0 3)"),
                               ("for i in xs {}", ["i"], "xs"),
                               ("for (k, v in d.items()) {}", ["k", "v"], "(call (. d items))"),
                               ("for ((k, v) in d.items()) {}", ["k", "v"], "(call (. d items))"),
                               ("for (k, v) in pairs {}", ["k", "v"], "pairs"),
                               ("for k, v in pairs {}", ["k", "v"], "pairs")]:
            with self.subTest(src=src):
                s = parse(src).body[0]
                self.assertEqual((s.names, sx(s.iter)), (names, it))

    def test_declarations(self):
        body = parse('val x: int = 1\nvar y\nvar z: list[str]? = null\n'
                     'fun f(a: int, b = 2) -> int { return a }\n'
                     'llm m = llm.Model("qwen3.5-4b")\nllm fast\nvector_store db = rag.VectorStore()\n'
                     'import llm\nimport nn.functional as F\nimport py "numpy" as np\n').body
        self.assertEqual([type(s).__name__ for s in body],
                         ["VarDecl", "VarDecl", "VarDecl", "FunDecl", "ResourceDecl", "ResourceDecl",
                          "ResourceDecl", "Import", "Import", "PyImport"])
        self.assertEqual((body[0].type.name, body[0].mutable), ("int", False))
        self.assertIsNone(body[1].value)
        self.assertEqual((body[2].type.name, body[2].type.args[0].name, body[2].type.nullable), ("list", "str", True))
        self.assertEqual([(p.name, p.default is not None) for p in body[3].params], [("a", False), ("b", True)])
        self.assertEqual(body[3].ret.name, "int")
        self.assertEqual((body[4].kind, body[4].name), ("llm", "m"))
        self.assertIsNone(body[5].value)
        self.assertEqual((body[8].path, body[8].alias), (["nn", "functional"], "F"))
        self.assertEqual((body[9].module, body[9].alias), ("numpy", "np"))

    def test_model_is_a_name_outside_declarations(self):
        body = parse("val model = 1\nprint(model)\nllm.Model()").body
        self.assertEqual([type(s).__name__ for s in body], ["VarDecl", "ExprStmt", "ExprStmt"])

    def test_class_and_model(self):
        body = parse("class P {\n  var x = 0\n  val name: str\n  fun inc() { x += 1 }\n}\n"
                     "model Net {\n  val l1 = nn.Linear(4, 2)\n  graph forward(x) { return l1(x) }\n}").body
        cls, model = body
        self.assertEqual(([f.name for f in cls.fields], [m.name for m in cls.methods], cls.is_model),
                         (["x", "name"], ["inc"], False))
        self.assertEqual((model.is_model, model.methods[0].kind), (True, "graph"))

    def test_assignments(self):
        body = parse("x = 1\nxs[0] = 2\no.f = 3\nx += 1\nxs[1:2] = []").body
        self.assertEqual([type(s).__name__ for s in body], ["Assign", "Assign", "Assign", "AugAssign", "Assign"])
        self.assertEqual(body[3].op, "+")


class ErrorsTest(UpsilTestCase):
    def test_expected_expression_with_position(self):
        self.assertEqual(parse_error("print(1 + )"), ("unexpected ')' — expected an expression", 1, 11))

    def test_russian_message(self):
        with lang("ru"):
            try:
                parse("print(1 + )")
            except CompileError as e:
                text = e.format()
        self.assertIn("<input>:1:11: ошибка: неожиданный токен ')' — ожидалось выражение", text)
        self.assertIn("  1 | print(1 + )\n    |           ^", text)

    def test_messages(self):
        cases = [
            ("a < b < c", "comparisons cannot be chained", 1, 7),
            ("a..b..c", "ranges cannot be chained", 1, 5),
            ("val x", "val 'x' needs a value", 1, 5),
            ("f(a = 1, 2)", "a positional argument cannot follow a named one", 1, 10),
            ("f(a = 1, a = 2)", "argument 'a' is given twice", 1, 10),
            ("print(1) print(2)", "expected the end of the statement", 1, 10),
            ("[a, b] => \"x\"", "a prompt takes exactly one model", 1, 1),
            ("[m, temp: 1] => \"x\"", "unknown prompt option 'temp'", 1, 5),
            ("[m] => \"x\" -> yaml", "after a prompt: '-> json', '-> choice([...])'", 1, 15),
            ("[m, system: 1]", "only allowed in a prompt", 1, 5),
            ("f() = 1", "cannot assign to this expression", 1, 1),
            ("fun (a) {}", "expected a function name", 1, 5),
            ("graph f(x) {}", "graph methods are only allowed inside a model", 1, 1),
            ("class A {\n  print(1)\n}", "a class body may contain only fields", 2, 3),
            ("class A {\n  graph f() {}\n}", "graph methods are only allowed inside a model", 2, 3),
            ("else {}", "'else' without 'if'", 1, 1),
            ("for x xs {}", "expected 'in'", 1, 7),
            ("if x\n  y()", "expected '{'", 2, 3),
            ("o.from", "'from' cannot be an attribute name", 1, 3),
            ("f(from = 1)", "'from' cannot be an argument name", 1, 3),
            ("val fun = 1", "'fun' is a keyword", 1, 5),
            ("x = ()", "empty parentheses", 1, 6),
            ("a == not b", "put 'not ...' in parentheses", 1, 6),
            ("a ? b", "unexpected '?'", 1, 3),
            ("a = b = 1", "expected the end of the statement", 1, 7),
            ("a + not b", "put 'not ...' in parentheses", 1, 5),
        ]
        for src, fragment, line, col in cases:
            with self.subTest(src=src):
                msg, l, c = parse_error(src)
                self.assertIn(fragment, msg)
                self.assertEqual((l, c), (line, col), msg)

    def test_end_of_file_is_incomplete(self):
        for src in ("val x =", "fun f() {", "x = [1,", "if a"):
            with self.subTest(src=src):
                try:
                    parse(src)
                except CompileError as e:
                    self.assertTrue(e.incomplete, e.format())
                else:
                    self.fail("no error")


if __name__ == "__main__":
    unittest.main()
