# SPDX-License-Identifier: Apache-2.0
import ast
import os
import subprocess
import sys
import tempfile
import traceback
import unittest

from support import ROOT, UpsilTestCase, clean_env, lang, run_upl

from upsil.compiler import compile_source
from upsil.errors import UpsilError


class ExpressionsTest(UpsilTestCase):
    def test_arithmetic_and_precedence(self):
        self.assertRuns("print((1 + 2) * 3, 1 + 2 * 3, 2 ** 3 ** 2, -2 ** 2, 7 / 2, div(7, 2), 7 % 3, -7 % 3)",
                        "9 7 512 -4 3.5 3 1 2\n")

    def test_values_are_shown_the_upsil_way(self):
        self.assertRuns('print(true, false, null, [1, "a", true, null], {"k": [1.5]}, 0..3, "x")',
                        'true false null [1, "a", true, null] {"k": [1.5]} 0..3 x\n')

    def test_str_builtin(self):
        self.assertRuns('print(str(true) + "!", str([1, "x"]), str(3.0), isinstance("a", str), str(), len(str(12)))',
                        'true! [1, "x"] 3.0 true  2\n')

    def test_interpolation(self):
        self.assertRuns('val name = "Макс"\nval xs = [1, 2]\n'
                        'print("Привет, {name}! {1 + 2} {xs} {true} {null} {3.14159:.2f} {7:>3}|")',
                        "Привет, Макс! 3 [1, 2] true null 3.14   7|\n")

    def test_interpolation_with_nested_strings(self):
        self.assertRuns('val d = {"k": "v"}\nprint("value: {d["k"]} and {"x" + "y"}")', "value: v and xy\n")

    def test_escaped_braces(self):
        self.assertRuns(r'print("\{x\} {1}")', "{x} 1\n")

    def test_triple_quoted(self):
        self.assertRuns('val who = "мир"\nval p = """\n    Привет, {who}!\n      "кавычки"\n    """\nprint(p)',
                        'Привет, мир!\n  "кавычки"\n')

    def test_comparisons_and_null(self):
        self.assertRuns('val x = null\nprint(x == null, x != null, null == x, 1 < 2, "a" in "abc", 3 not in [1, 2])',
                        "true false true true true true\n")

    def test_and_or_return_operands(self):
        self.assertRuns('print(null or "default", 0 and 5, not 0)', "default 0 true\n")

    def test_ranges(self):
        self.assertRuns("var s = []\nfor (i in 0..3) { s.append(i) }\nfor i in 5..=6 { s.append(i) }\n"
                        "for (i in 3..0) { s.append(99) }\nprint(s, 2 in 1..3, 3 in 1..3, list(1..=3))",
                        "[0, 1, 2, 5, 6] true false [1, 2, 3]\n")

    def test_indexing_and_slicing(self):
        self.assertRuns('val xs = [10, 20, 30, 40]\nprint(xs[0], xs[-1], xs[1:3], xs[:2], xs[::2], "abc"[1], [[1, 2], [3, 4]][1][0])',
                        "10 40 [20, 30] [10, 20] [10, 30] b 3\n")

    def test_dicts_and_methods(self):
        self.assertRuns('val d = {"a": 1}\nd["b"] = 2\nd["a"] += 10\nprint(d, d.get("z", 0), sorted(d.keys()), ", ".join(["x", "y"]))',
                        '{"a": 11, "b": 2} 0 ["a", "b"] x, y\n')

    def test_method_chains_across_lines(self):
        self.assertRuns('val s = "  Hello World  "\nval t = s\n  .strip()\n  .lower()\n  .replace("world", "upsil")\nprint(t)',
                        "hello upsil\n")

    def test_keyword_arguments_to_python_builtins(self):
        self.assertRuns("print(sorted([3, 1, 2], reverse = true), round(2.567, 2), max([1, 5, 2]))", "[3, 2, 1] 2.57 5\n")

    def test_print_sep_and_end(self):
        self.assertRuns('print(1, 2, sep = "-", end = "!")\nprint()', "1-2!\n")

    def test_unicode_names(self):
        self.assertRuns('val имя = "Мир"\nfun приветствие(кому) { return "Привет, {кому}!" }\nprint(приветствие(имя))',
                        "Привет, Мир!\n")


class LanguageDetailsTest(UpsilTestCase):
    def test_bom_and_crlf(self):
        self.assertRuns("\ufeffprint(1)\r\nprint(2)\r\n", "1\n2\n")

    def test_compound_assignments(self):
        self.assertRuns("var x = 10\nx += 5\nx -= 3\nx *= 2\nx /= 4\nvar y = 17\ny %= 5\nprint(x, y)", "6.0 2\n")

    def test_matmul_operator(self):
        tree = compile_source("fun f(a, b) { return a @ b }", "m.upl").tree
        ops = [n.op for n in ast.walk(tree) if isinstance(n, ast.BinOp)]
        self.assertTrue(any(isinstance(op, ast.MatMult) for op in ops))

    def test_tuple_indexes(self):
        self.assertRuns("val grid = {}\ngrid[1, 2] = \"x\"\nprint(grid[1, 2], len(grid))", "x 1\n")

    def test_truthiness(self):
        self.assertRuns('for (v in [false, null, 0, 0.0, "", [], {}, 1, "a", [0]]) { if v { print("T", end = "") } else { print("F", end = "") } }',
                        "FFFFFFFTTT")

    def test_plus_does_not_join_a_string_and_a_number(self):
        with self.assertRaises(TypeError):
            run_upl('print("a" + 1)')
        self.assertRuns('print("a" + str(1), "a{1}")', "a1 a1\n")

    def test_every_builtin_exists_at_run_time(self):
        from upsil.keywords import BUILTINS
        src = "val all_builtins = [" + ", ".join(BUILTINS) + "]\nprint(len(all_builtins))"
        self.assertRuns(src, f"{len(BUILTINS)}\n")

    def test_closures_capture_variables_not_values(self):
        # documented limitation of v0.2 (as in Python): a function made in a loop sees the last value
        self.assertRuns("val fs = []\nfor (i in 0..3) {\n  fun get() { return i }\n  fs.append(get)\n}\n"
                        "print(fs[0](), fs[2]())", "2 2\n")

    def test_prompt_text_is_shown_as_a_string(self):
        self.assertRuns(PromptOperatorTest.ECHO + "val m = Echo()\nprint([m] => [1, true])", '[null] [1, true]\n')


class StatementsTest(UpsilTestCase):
    def test_newlines_end_statements(self):
        self.assertRuns("val x = 5\n-3\nprint(x)", "5\n")

    def test_if_else_chain(self):
        src = 'fun size(n) {\n  if n > 10 { return "big" } else if n > 1 { return "mid" } else { return "small" }\n}\n' \
              'print(size(50), size(5), size(0))'
        self.assertRuns(src, "big mid small\n")

    def test_while_break_continue(self):
        src = "var i = 0\nvar out = []\nwhile true {\n  i += 1\n  if i % 2 == 0 { continue }\n" \
              "  if i > 7 { break }\n  out.append(i)\n}\nprint(out)"
        self.assertRuns(src, "[1, 3, 5, 7]\n")

    def test_for_destructuring(self):
        self.assertRuns('for (k, v) in {"a": 1, "b": 2}.items() { print("{k}={v}") }\n'
                        'for i, ch in enumerate("ab") { print(i, ch) }', "a=1\nb=2\n0 a\n1 b\n")

    def test_empty_bodies(self):
        self.assertRuns("fun nothing() {}\nif true {} else {}\nwhile false {}\nclass Empty {}\nprint(nothing(), Empty())",
                        "null Empty()\n")

    def test_var_without_value_is_null(self):
        self.assertRuns("var x\nprint(x)\nx = 1\nprint(x)", "null\n1\n")


class FunctionsTest(UpsilTestCase):
    def test_defaults_and_keywords(self):
        self.assertRuns('fun greet(name, greeting = "Hi", punct = "!") { return "{greeting}, {name}{punct}" }\n'
                        'print(greet("A"), greet("B", punct = "?"), greet(greeting = "Yo", name = "C"))',
                        "Hi, A! Hi, B? Yo, C!\n")

    def test_defaults_are_evaluated_at_each_call(self):
        self.assertRuns("fun add(x, xs = []) { xs.append(x)\n return xs }\nprint(add(1), add(2))", "[1] [2]\n")

    def test_default_may_use_earlier_parameter(self):
        self.assertRuns("fun area(w, h = w) { return w * h }\nprint(area(3), area(3, 4))", "9 12\n")

    def test_closures_and_nonlocal(self):
        self.assertRuns("fun counter() {\n  var n = 0\n  fun inc() {\n    n += 1\n    return n\n  }\n  return inc\n}\n"
                        "val c = counter()\nc()\nprint(c(), counter()())", "2 1\n")

    def test_functions_assign_module_vars(self):
        self.assertRuns("var total = 0\nfun add(x) { total += x }\nadd(2)\nadd(3)\nprint(total)", "5\n")

    def test_mutual_recursion(self):
        self.assertRuns("fun even(n) { if n == 0 { return true }\n return odd(n - 1) }\n"
                        "fun odd(n) { if n == 0 { return false }\n return even(n - 1) }\nprint(even(10), odd(7))",
                        "true true\n")

    def test_nested_functions(self):
        self.assertRuns("fun outer(x) {\n  fun twice(y) { return y * 2 }\n  return twice(x) + 1\n}\nprint(outer(4))", "9\n")


class ScopingTest(UpsilTestCase):
    """UpsiL block scopes on top of Python function scopes."""

    def test_block_local_next_to_global(self):
        src = 'val x = "global"\nfun f() {\n  print(x)\n  if true {\n    val x = "local"\n    print(x)\n  }\n  print(x)\n}\nf()'
        self.assertRuns(src, "global\nlocal\nglobal\n")

    def test_block_local_named_like_a_builtin(self):
        src = "fun f(xs) {\n  if len(xs) > 0 {\n    val len = 10\n    print(len)\n  }\n  return len(xs)\n}\nprint(f([1, 2]))"
        self.assertRuns(src, "10\n2\n")

    def test_parameter_named_range(self):
        self.assertRuns("fun f(range) {\n  var total = 0\n  for (i in 0..3) { total += i }\n  return total + range\n}\n"
                        "print(f(10))", "13\n")

    def test_local_named_range(self):
        self.assertRuns("fun f() {\n  val range = 100\n  var t = 0\n  for (i in 1..=3) { t += i }\n  return t + range\n}\n"
                        "print(f())", "106\n")

    def test_sibling_blocks_captured_by_closures(self):
        src = ('fun f() {\n  val fs = []\n'
               '  if true {\n    val v = "a"\n    fun g() { return v }\n    fs.append(g)\n  }\n'
               '  if true {\n    val v = "b"\n    fun h() { return v }\n    fs.append(h)\n  }\n  return fs\n}\n'
               'for (fn in f()) { print(fn()) }')
        self.assertRuns(src, "a\nb\n")

    def test_user_function_named_like_a_builtin(self):
        self.assertRuns('fun print2(x) { print("<{x}>") }\nfun len(x) { return 42 }\nprint2(len([1]))', "<42>\n")


class ClassesTest(UpsilTestCase):
    def test_fields_constructor_and_methods(self):
        src = ('class Counter {\n  val name: str\n  var count = 0\n'
               '  fun inc(by = 1) {\n    count += by\n    return self.count\n  }\n'
               '  fun label() { return "{name}: {count}" }\n}\n'
               'val c = Counter("clicks")\nc.inc()\nc.inc(by = 5)\nprint(c.label(), c.count, c)')
        self.assertRuns(src, 'clicks: 6 6 Counter(name="clicks", count=6)\n')

    def test_initializers_use_earlier_fields_and_methods(self):
        src = ('class Box {\n  val w\n  val h\n  val area = w * h\n  val label = describe()\n'
               '  fun describe() { return "{w}x{h}" }\n}\nval b = Box(2, h = 3)\nprint(b.area, b.label)')
        self.assertRuns(src, "6 2x3\n")

    def test_instances_are_independent(self):
        self.assertRuns("class Bag {\n  val items = []\n  fun add(x) { items.append(x) }\n}\n"
                        "val a = Bag()\nval b = Bag()\na.add(1)\nprint(a.items, b.items)", "[1] []\n")

    def test_methods_call_each_other_and_module_functions(self):
        src = ("fun double(x) { return x * 2 }\nclass Calc {\n  var acc = 1\n  fun step() { acc = double(acc)\n return self }\n"
               "  fun run(n) { for (i in 0..n) { step() }\n return acc }\n}\nprint(Calc().run(3))")
        self.assertRuns(src, "8\n")


class PromptOperatorTest(UpsilTestCase):
    """The prompt operator calls `ask` on any object that has one."""

    ECHO = ('class Echo {\n  fun ask(text, system = null, json = false) {\n'
            '    if json { return {"text": text} }\n    return "[{system}] {text}"\n  }\n}\n')

    def test_prompt(self):
        self.assertRuns(self.ECHO + 'val m = Echo()\nval q = "RAG"\nprint([m] => "Explain {q} in {1 + 1} words")',
                        "[null] Explain RAG in 2 words\n")

    def test_prompt_with_system_and_json(self):
        self.assertRuns(self.ECHO + 'val m = Echo()\nprint([m, system: "terse"] => "hi")\nprint([m] => "hi" -> json)',
                        '[terse] hi\n{"text": "hi"}\n')

    def test_multiline_prompt(self):
        self.assertRuns(self.ECHO + 'llm m = Echo()\nval doc = "text"\nprint([m] => """\n    Summarize:\n    {doc}\n    """)',
                        "[null] Summarize:\ntext\n")

    def test_prompt_needs_a_model(self):
        with self.assertRaises(UpsilError) as cm, lang("en"):
            run_upl('print([5] => "x")')
        self.assertIn("must be an llm model", str(cm.exception))

    def test_llm_declaration_checks_the_value(self):
        with self.assertRaises(UpsilError) as cm, lang("en"):
            run_upl('llm m = "qwen"')
        self.assertIn("llm m: expected an llm model", str(cm.exception))


class RuntimeBehaviourTest(UpsilTestCase):
    def test_input_returns_null_at_end_of_input(self):
        self.assertRuns('val a = input()\nval b = input()\nprint(a, b == null)', "hello true\n", stdin="hello\n")

    def test_error_builtin(self):
        with self.assertRaises(UpsilError) as cm:
            run_upl('error("bad input: {42}")')
        self.assertEqual(str(cm.exception), "bad input: 42")

    def test_python_imports(self):
        self.assertRuns('import py "math" as pm\nimport py "os.path"\nprint(pm.sqrt(16), os.path.basename("/a/b.txt"))',
                        "4.0 b.txt\n")

    def test_traceback_points_at_upsil_source(self):
        src = "fun main() {\n    val x = 0\n    print(1 / x)\n}\nmain()\n"
        program = compile_source(src, "div.upl")
        try:
            exec(program.code, {"__name__": "__main__"})
        except ZeroDivisionError as exc:
            frames = traceback.extract_tb(exc.__traceback__)
        else:
            self.fail("no error")
        last = frames[-1]
        self.assertEqual((last.filename, last.lineno, last.name, last.line), ("div.upl", 3, "main", "print(1 / x)"))
        self.assertEqual((frames[-2].lineno, frames[-2].name), (5, "<module>"))
        if sys.version_info >= (3, 11):
            self.assertEqual((last.colno, last.end_colno), (10, 15))   # the columns of `1 / x`

    def test_columns_are_utf8_byte_offsets(self):
        src = 'val s = "привет"\nprint(s + 1)\n'
        program = compile_source(src, "u.upl")
        binop = [n for n in ast.walk(program.tree) if isinstance(n, ast.BinOp)][0]
        self.assertEqual((binop.lineno, binop.col_offset, binop.end_col_offset), (2, 6, 11))
        src = 'val s = "привет" + 1\n'
        program = compile_source(src, "u.upl")
        binop = [n for n in ast.walk(program.tree) if isinstance(n, ast.BinOp)][0]
        self.assertEqual((binop.col_offset, binop.end_col_offset), (8, 8 + len('"привет" + 1'.encode())))


class BuildOutputTest(UpsilTestCase):
    SOURCE = ('val xs: list[int] = [3, 1, 2]\nvar total = 0\nfun add(x: int) -> int {\n  total += x\n  return total\n}\n'
              'for (x in xs) { add(x) }\nval d = {"k": "v"}\nprint("total={total} {d["k"]} {true}")\n'
              'class P {\n  val n\n}\nprint(P(1))\n')

    def test_build_output_is_readable_python(self):
        text = compile_source(self.SOURCE, "b.upl").python_source()
        self.assertTrue(text.startswith("# Generated by UpsiL 0.2.0 from b.upl"))
        self.assertIn("def add(x: int) -> int:\n    global total\n    total += x", text)
        self.assertIn("for x in xs:", text)
        self.assertIn("xs: list[int] = [3, 1, 2]", text)
        self.assertIn("from upsil.runtime.prelude import print", text)
        self.assertNotIn("eval(", text)
        self.assertNotIn("exec(", text)

    def test_build_output_runs_the_same_on_every_python(self):
        text = compile_source(self.SOURCE, "b.upl").python_source()
        expected = run_upl(self.SOURCE)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "b.py")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            result = subprocess.run([sys.executable, path], capture_output=True, text=True, env=clean_env(),
                                    encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected)
        self.assertEqual(expected, 'total=6 v true\nP(n=1)\n')


if __name__ == "__main__":
    unittest.main()
