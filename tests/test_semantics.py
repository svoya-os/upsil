# SPDX-License-Identifier: Apache-2.0
import unittest

from support import UpsilTestCase, lang

from upsil.checker import check
from upsil.errors import CompileError
from upsil.parser import parse


def diagnostics(src, lint=False, language="en"):
    with lang(language):
        try:
            check(parse(src, "t.upl"), "t.upl", src, lint_types=lint)
        except CompileError as e:
            return [(d.message, d.span.line, d.span.col) for d in e.diagnostics]
    return []


class SemanticsTest(UpsilTestCase):
    def assertError(self, src, fragment, line=None, col=None, lint=False):
        diags = diagnostics(src, lint)
        matching = [d for d in diags if fragment in d[0]]
        self.assertTrue(matching, f"{fragment!r} not in {diags!r}")
        if line is not None:
            self.assertEqual(matching[0][1], line, matching[0])
        if col is not None:
            self.assertEqual(matching[0][2], col, matching[0])

    def assertOk(self, src, lint=False):
        self.assertEqual(diagnostics(src, lint), [])

    # ---------------------------------------------------------------- names
    def test_undefined_name(self):
        self.assertError("val x = 1\nprint(y)", "undefined name 'y'", 2, 7)

    def test_suggestion(self):
        self.assertError("val count = 1\nprint(cuont)", "did you mean 'count'?")

    def test_missing_import_hint(self):
        self.assertError('val m = llm.Model()', "add `import llm`")

    def test_names_inside_interpolation_are_checked(self):
        self.assertError('print("a {nope} b")', "undefined name 'nope'", 1, 11)

    def test_use_before_declaration(self):
        self.assertError("print(x)\nval x = 1", "'x' is used before its declaration (line 2)", 1, 7)
        self.assertError("f()\nfun f() {}", "'f' is used before its declaration")

    def test_functions_see_later_declarations(self):
        self.assertOk("fun a() { return b() + limit }\nfun b() { return 1 }\nval limit = 3\nprint(a())")

    def test_recursion(self):
        self.assertOk("fun fact(n) { if n < 2 { return 1 }\n return n * fact(n - 1) }")

    def test_block_scope(self):
        self.assertError("if true {\n  val t = 1\n}\nprint(t)", "undefined name 't'", 4)
        self.assertError("for (i in 0..3) {}\nprint(i)", "undefined name 'i'")

    def test_nested_function_does_not_see_other_blocks(self):
        self.assertError("fun f() {\n  if true { val z = 1 }\n  fun g() { return z }\n}", "undefined name 'z'")

    def test_multiple_errors_are_reported_together(self):
        diags = diagnostics("print(a)\nprint(b)")
        self.assertEqual([(m, l) for m, l, _ in diags], [("undefined name 'a'", 1), ("undefined name 'b'", 2)])

    # ---------------------------------------------------------------- declarations
    def test_duplicate_declaration(self):
        self.assertError("val a = 1\nvar a = 2", "'a' is already declared in this scope (line 1)", 2)
        self.assertError("fun f() {}\nfun f() {}", "'f' is already declared")

    def test_shadowing_in_the_same_function(self):
        self.assertError("val x = 1\nif true {\n  val x = 2\n}", "'x' shadows a variable of an enclosing block (line 1)", 3)
        self.assertError("for (i in 0..2) {\n  for (i in 0..2) {}\n}", "'i' shadows")

    def test_sibling_blocks_and_functions_may_reuse_names(self):
        self.assertOk("for (i in 0..2) {}\nfor (i in 0..3) {}\nval i = 5\n"
                      "fun f(i) { return i }\nfun g() { val i = 1\n return i }")

    def test_reserved_names(self):
        self.assertError("val lambda = 1", "'lambda' is a reserved word (a Python keyword)")
        self.assertError("val _upsil_x = 1", "reserved for the compiler")
        self.assertError("val self = 1", "'self' is reserved")
        self.assertError("fun super() {}", "'super' is reserved")
        self.assertError("print(None)", "'None' is a reserved word")

    # ---------------------------------------------------------------- assignments
    def test_val_reassignment(self):
        self.assertError("val x = 1\nx = 2", "cannot reassign val 'x' (declared at line 1)", 2, 1)
        self.assertError("val x = 1\nx += 2", "cannot reassign val 'x'")
        self.assertError("import llm\nllm m\nm = 1", "cannot reassign val 'm'")

    def test_var_is_assignable_and_val_objects_are_mutable(self):
        self.assertOk("var x = 1\nx = 2\nx += 1\nval xs = [1]\nxs[0] = 5\nxs.append(2)")

    def test_assign_to_undeclared(self):
        self.assertError("y = 1", "cannot assign to undeclared 'y'; declare it first: var y = ...")

    def test_read_only_names(self):
        self.assertError("fun f(a) { a = 1 }", "cannot assign to parameter 'a'")
        self.assertError("for (i in 0..3) { i = 1 }", "cannot assign to loop variable 'i'")
        self.assertError("fun f() {}\nf = 1", "cannot assign to function 'f'")
        self.assertError("class C {}\nC = 1", "cannot assign to class 'C'")
        self.assertError("import math\nmath = 1", "cannot assign to imported module 'math'")
        self.assertError("print = 1", "cannot assign to built-in function 'print'")

    def test_nested_function_may_assign_outer_var(self):
        self.assertOk("fun counter() {\n  var n = 0\n  fun inc() { n += 1\n return n }\n  return inc\n}")

    # ---------------------------------------------------------------- control flow
    def test_break_and_continue_outside_loop(self):
        self.assertError("break", "'break' outside a loop", 1, 1)
        self.assertError("fun f() { continue }", "'continue' outside a loop")
        self.assertError("while true {\n  fun g() { break }\n}", "'break' outside a loop", 2)

    def test_return_outside_function(self):
        self.assertError("return 1", "'return' outside a function", 1, 1)

    def test_loop_control_inside_loops(self):
        self.assertOk("fun f() {\n  for (i in 0..3) { if i == 1 { continue }\n break }\n  while true { break }\n return 1 }")

    # ---------------------------------------------------------------- functions
    def test_duplicate_params(self):
        self.assertError("fun f(a, a) {}", "duplicate parameter 'a'", 1, 10)

    def test_param_order(self):
        self.assertError("fun f(a = 1, b) {}", "parameter 'b' without a default follows")

    def test_param_redeclared_in_body(self):
        self.assertError("fun f(a) { val a = 2 }", "'a' is already declared")

    def test_defaults_may_use_earlier_params(self):
        self.assertOk("fun f(a, b = a * 2) { return b }")
        self.assertError("fun f(a = b, b = 1) { return a }", "'b' is used before its declaration")

    def test_arity(self):
        self.assertError("fun f(a, b = 1) {}\nf(1, 2, 3)", "f() takes 2 arguments but 3 were given", 2)
        self.assertError("fun f(a, b = 1) {}\nf()", "f() is missing the argument 'a'")
        self.assertError("fun f(a) {}\nf(1, z = 2)", "f() has no parameter 'z'")
        self.assertError("fun f(a) {}\nf(1, a = 2)", "f() got the argument 'a' twice")
        self.assertOk("fun f(a, b = 1) {}\nf(1)\nf(b = 2, a = 1)")

    def test_arity_in_russian(self):
        self.assertEqual(diagnostics("fun f(a) {}\nf(1, 2)", language="ru")[0][0],
                         "f() принимает 1 аргумент, а получено аргументов: 2")

    # ---------------------------------------------------------------- classes and models
    def test_class_fields_and_methods(self):
        self.assertOk("class Counter {\n  val name: str\n  var count = 0\n"
                      "  fun inc(by = 1) { count += by\n return self.count }\n"
                      "  fun label() { return \"{name}: {count}\" }\n}\n"
                      "val c = Counter(\"a\")\nc.inc()\nprint(c.label())")

    def test_val_field_is_read_only(self):
        self.assertError("class C {\n  val x = 1\n  fun f() { x = 2 }\n}", "cannot reassign val field 'x'", 3)
        self.assertError("class C {\n  val x = 1\n  fun f() { self.x = 2 }\n}", "cannot reassign val field 'x'", 3)
        self.assertError("class C {\n  fun m() {}\n  fun f() { m = 2 }\n}", "cannot assign to method 'm'")

    def test_field_initializers_are_sequential(self):
        self.assertError("class C {\n  val a = b\n  val b = 1\n}", "'b' is used before its declaration")
        self.assertOk("class C {\n  val a = make()\n  fun make() { return 1 }\n}")

    def test_constructor_arity(self):
        self.assertError("class P {\n  val x\n  val y\n}\nP(1)", "P() is missing the argument 'y'")
        self.assertError("class P {\n  var n = 0\n}\nP(n = 1)", "P() has no parameter 'n'")

    def test_self_outside_methods(self):
        self.assertError("print(self)", "'self' is only available inside methods")

    def test_model_needs_forward(self):
        self.assertError("import nn\nmodel Net {\n  val l = nn.Linear(1, 1)\n}", "model 'Net' has no forward(...) method", 2)

    def test_model_ok(self):
        self.assertOk("import nn\nmodel Net {\n  val l1 = nn.Linear(4, 8)\n  graph forward(x) { return l1(x) }\n}\n"
                      "val net = Net()")

    def test_classes_only_at_top_level(self):
        self.assertError("fun f() {\n  class C {}\n}", "classes and models can only be declared at the top level", 2)

    # ---------------------------------------------------------------- imports
    def test_imports(self):
        self.assertOk('import llm\nimport rag\nimport nn.functional as F\nimport py "os.path"\nimport py "numpy" as np\n'
                      'print(os.path.join("a", "b"))')
        self.assertError("import cortex.rag", "unknown module 'cortex'")
        self.assertError("import cortex.rag", 'import py "cortex.rag"')
        self.assertError("import nn.a.b as x", "import at most one level deep")
        self.assertError('import py "not a module"', "is not a valid Python module name")
        self.assertError("fun f() {\n  import llm\n}", "import is only allowed at the top level")

    # ---------------------------------------------------------------- type lint (upsil check)
    def test_type_lint(self):
        self.assertError('val x: int = "a"', "type mismatch: 'x' is declared as int but the value is a string",
                         1, 14, lint=True)
        self.assertError("val s: str = 1", "is declared as str but the value is an integer", lint=True)
        self.assertError("val s: string = 1", "is declared as string but the value is an integer", lint=True)
        self.assertError('fun f(a: int = "x") {}', "parameter 'a' is declared as int", lint=True)
        self.assertError('fun f() -> int { return "x" }', "the result of f() is declared as int", lint=True)
        self.assertError('class C {\n  val n: bool = [1]\n}', "is declared as bool but the value is a list", lint=True)
        self.assertOk("val f: float = 1\nval t: tensor = 5\nval n: int = -3\nval o: int? = null", lint=True)
        self.assertOk('val x: int = "a"')   # run/build do not lint types: the runtime is dynamic

    def test_type_lint_in_russian(self):
        self.assertEqual(diagnostics('val x: int = "a"', lint=True, language="ru")[0][0],
                         "несовпадение типов: у 'x' указан тип int, а значение — строка")


if __name__ == "__main__":
    unittest.main()
