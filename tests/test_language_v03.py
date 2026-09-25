# SPDX-License-Identifier: Apache-2.0
"""UpsiL 0.3: errors (try/catch/finally/throw, assert), with, lambdas, comprehensions,
if-expressions, tuples and destructuring, raw strings, imports of .upl files."""

import os
import tempfile
import textwrap
import unittest

from support import UpsilTestCase, lang, run_cli, run_upl

from upsil.compiler import compile_source
from upsil.errors import UpsilError


class ErrorsTest(UpsilTestCase):
    def test_catch_by_type_and_finally(self):
        self.assertRuns(textwrap.dedent('''\
            fun risky(n) {
                if n == 1 { throw "один" }
                if n == 2 { throw ValueError("два") }
                return n
            }
            for (i in 0..3) {
                try {
                    print("ok", risky(i))
                } catch (e: ValueError) {
                    print("value:", e)
                } catch (e) {
                    print("other:", e)
                } finally {
                    print("end", i)
                }
            }
            '''), "ok 0\nend 0\nother: один\nend 1\nvalue: два\nend 2\n")

    def test_catch_without_a_name_and_python_errors(self):
        self.assertRuns('val zero = 0\ntry { print(1 / zero) } catch { print("поймали") }\n'
                        'try { print([1][5]) } catch (e: IndexError) { print("индекс") }\n'
                        'try { print({"a": 1}["b"]) } catch (e: KeyError) { print("ключ", e) }',
                        "поймали\nиндекс\nключ 'b'\n")

    def test_rethrow_and_error_objects(self):
        self.assertRuns(textwrap.dedent('''\
            fun inner() {
                try { error("сломалось") } catch (e) { print("лог:", e); throw }
            }
            try { inner() } catch (e: Error) { print("снаружи:", e) }
            try { throw RuntimeError } catch (e: RuntimeError) { print("тип:", isinstance(e, RuntimeError)) }
            '''), "лог: сломалось\nснаружи: сломалось\nтип: true\n")

    def test_uncaught_throw_is_a_runtime_error(self):
        with lang("en"):
            program = compile_source('throw "всё пропало"', "t.upl")
            with self.assertRaises(UpsilError) as ctx:
                exec(program.code, {"__name__": "__main__"})
            self.assertEqual(str(ctx.exception), "всё пропало")

    def test_a_closure_keeps_the_caught_error(self):
        # Python deletes `except ... as e` at the end of the handler; UpsiL keeps it
        self.assertRuns('val later = []\ntry { throw "ошибка" } catch (e) { later.append(() => e) }\n'
                        'fun f() {\n  try { error("в функции") } catch (e) { return () => "{e}!" }\n}\n'
                        'print(later[0](), f()())', "ошибка в функции!\n")

    def test_ctrl_c_and_exit_are_not_caught(self):
        with self.assertRaises(SystemExit):
            run_upl('import sys\ntry { sys.exit(3) } catch (e) { print("не должно") }')

    def test_bare_throw_outside_catch(self):
        self.assertCompileError("throw", "a bare 'throw' re-throws the caught error", 1, 1)
        self.assertCompileError('try { print(1) } catch (e) {\n  fun f() { throw }\n}',
                                "a bare 'throw' re-throws", 2, 13)

    def test_try_needs_catch_or_finally(self):
        self.assertCompileError("try { print(1) }", "'try' needs a 'catch' or a 'finally'")
        self.assertCompileError("catch (e) { }", "'catch' without 'try'")

    def test_caught_error_is_read_only_and_block_scoped(self):
        self.assertCompileError('try { print(1) } catch (e) { e = 1 }', "cannot assign to caught error 'e'")
        self.assertCompileError('try { print(1) } catch (e) { }\nprint(e)', "undefined name 'e'", 2)

    def test_assert(self):
        self.assertRuns('assert 1 + 1 == 2\nprint("ок")', "ок\n")
        with lang("en"):
            program = compile_source('val x = 3\nassert x > 5, "x = {x} is too small"', "t.upl")
            with self.assertRaises(AssertionError) as ctx:
                exec(program.code, {"__name__": "__main__"})
            self.assertEqual(str(ctx.exception), "x = 3 is too small")
            program = compile_source('val xs = []\nassert len(xs) >\n  0', "t.upl")
            with self.assertRaises(AssertionError) as ctx:
                exec(program.code, {"__name__": "__main__"})
            self.assertEqual(str(ctx.exception), "assertion failed: len(xs) > 0")
        self.assertRuns('try { assert false } catch (e: AssertionError) { print("assert") }', "assert\n")


class WithTest(UpsilTestCase):
    def test_context_managers(self):
        self.assertRuns(textwrap.dedent('''\
            class Res {
                val name: str
                fun __enter__() { print("открыл", name); return self }
                fun __exit__(kind, value, tb) { print("закрыл", name); return false }
            }
            with Res("a") as a, Res("b") {
                print("внутри", a.name)
            }
            with (Res("c") as c) {
                print(c.name)
            }
            try {
                with Res("d") { throw "ой" }
            } catch (e) { print("после:", e) }
            '''), "открыл a\nоткрыл b\nвнутри a\nзакрыл b\nзакрыл a\nоткрыл c\nc\nзакрыл c\n"
                  "открыл d\nзакрыл d\nпосле: ой\n")

    def test_with_name_is_read_only(self):
        self.assertCompileError('import py "contextlib"\nwith contextlib.nullcontext(1) as x { x = 2 }',
                                "cannot assign to 'with ... as' name 'x'")


class FunctionalTest(UpsilTestCase):
    def test_lambdas(self):
        self.assertRuns(textwrap.dedent('''\
            val double = x => x * 2
            val add = (a, b) => a + b
            val answer = () => 42
            val typed = (s: str) => s.upper()
            print(double(21), add(1, 2), answer(), typed("ok"))
            print(sorted(["банан", "яблоко", "киви"], key = w => len(w)))
            print(list(map(n => n * n, 1..=3)), list(filter(n => n % 2 == 0, 0..5)))
            fun make(k) { return x => x * k }
            print(make(3)(5))
            '''), '42 3 42 OK\n["киви", "банан", "яблоко"]\n[1, 4, 9] [0, 2, 4]\n15\n')

    def test_lambda_sees_names_declared_later(self):
        self.assertRuns('val f = () => limit * 2\nval limit = 21\nprint(f())', "42\n")

    def test_comprehensions(self):
        self.assertRuns(textwrap.dedent('''\
            val xs = [3, 1, 4, 1, 5]
            print([x * x for x in xs if x > 1])
            print([x for (x in xs) if x % 2 == 1 if x > 1])
            print({w: len(w) for w in ["аб", "в"]})
            print({k: v * 10 for (k, v) in {"a": 1}.items()})
            print([(i, c) for i, c in enumerate("аб")])
            print([a * b for a in 1..=2 for b in 1..=3])
            print(sum(x for x in xs), max(len(w) for w in ["a", "bcd"]))
            val g = (x * 2 for x in xs)
            print(list(g))
            '''), '[9, 16, 25]\n[3, 5]\n{"аб": 2, "в": 1}\n{"a": 10}\n[(0, "а"), (1, "б")]\n'
                  '[1, 2, 3, 2, 4, 6]\n14 3\n[6, 2, 8, 2, 10]\n')

    def test_comprehension_variables_stay_inside(self):
        self.assertCompileError("val sq = [i * i for i in 0..3]\nprint(i)", "undefined name 'i'", 2)
        self.assertCompileError("print(f(x) for x in [1], 2)", "write a generator as the only argument")

    def test_if_expression(self):
        self.assertRuns(textwrap.dedent('''\
            fun sign(n) { return if (n > 0) "+" else if (n < 0) "-" else "0" }
            print(sign(5), sign(-2), sign(0))
            val label = if (len([1, 2]) > 1)
                "много"
                else "мало"
            print(label, [if (x % 2 == 0) "чёт" else "нечет" for x in 1..=3])
            '''), '+ - 0\nмного ["нечет", "чёт", "нечет"]\n')
        self.assertCompileError("val x = if (true) 1", "an if-expression needs 'else'")
        self.assertCompileError("val x = if true 1 else 2", "the condition of an if-expression goes in parentheses")
        self.assertRuns("val a = 2\nif (a > 1) print(\"да\") else print(\"нет\")", "да\n")
        self.assertCompileError("if (true) print(1)", "the body of an if statement goes in { }")
        self.assertCompileError("if true print(1)", "expected '{'")

    def test_tuples_and_destructuring(self):
        self.assertRuns(textwrap.dedent('''\
            fun min_max(xs) { return min(xs), max(xs) }
            val (lo, hi) = min_max([4, 2, 9])
            var (a, b) = 1, 2
            a, b = b, a
            (a, b) = (a * 10, b * 10)
            val single = (7,)
            print(lo, hi, a, b, single, (1, "два"), len(single))
            '''), '2 9 20 10 (7,) (1, "два") 1\n')
        self.assertCompileError("val (a, b) = (1, 2)\na = 5", "cannot reassign val 'a'")
        self.assertCompileError("val (a, a) = (1, 2)", "'a' is repeated")
        self.assertCompileError("val (a, b)", "val (...) needs a value")

    def test_raw_strings(self):
        self.assertRuns(r'print(r"\d{2}\n", len(r"\t"), r"""a"b{c}""")', '\\d{2}\\n 2 a"b{c}\n')


class ImportsTest(UpsilTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = self.dir.name

    def tearDown(self):
        self.dir.cleanup()

    def write(self, name, text):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(textwrap.dedent(text))
        return path

    def test_import_files_once(self):
        self.write("helpers.upl", '''\
            val greeting = "привет"
            fun shout(s) { return s.upper() + "!" }
            print("helpers загружен")
            ''')
        self.write("lib/data.upl", '''\
            import "../helpers.upl" as h
            fun rows() { return [h.shout("a"), h.shout("b")] }
            ''')
        main = self.write("main.upl", '''\
            import helpers
            import "lib/data.upl"
            import "helpers.upl" as again
            print(helpers.shout(helpers.greeting), data.rows(), again.greeting)
            ''')
        r = run_cli(["run", main], cwd=os.path.dirname(self.root))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, 'helpers загружен\nПРИВЕТ! ["A!", "B!"] привет\n')

    def test_missing_file_is_a_compile_error(self):
        main = self.write("main.upl", 'import "nope.upl"\n')
        r = run_cli(["run", main])
        self.assertEqual(r.returncode, 2)
        self.assertIn("file not found: nope.upl", r.stderr)

    def test_errors_in_an_imported_file(self):
        self.write("broken.upl", "val x = \n")
        main = self.write("main.upl", 'import "broken.upl"\n')
        r = run_cli(["run", main])
        self.assertEqual(r.returncode, 1)
        self.assertIn("errors in", r.stderr)
        self.assertIn("broken.upl:2:1: error: unexpected end of file", r.stderr)

    def test_cycles(self):
        self.write("a.upl", 'import "b.upl"\n')
        self.write("b.upl", 'import "a.upl"\n')
        r = run_cli(["run", os.path.join(self.root, "a.upl")])
        self.assertEqual(r.returncode, 1)
        self.assertIn("circular import", r.stderr)

    def test_import_needs_an_upl_file_and_a_name(self):
        self.assertCompileError('import "numpy"', 'import "..." takes an UpsiL file (.upl)')
        self.assertCompileError('import "my-lib.upl"', "is not a valid name")


if __name__ == "__main__":
    unittest.main()
