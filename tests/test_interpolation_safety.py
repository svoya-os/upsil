# SPDX-License-Identifier: Apache-2.0
"""User text is data, never code.

v0.1 pasted string literals into Python f-strings, so "{...}" in a string
ran arbitrary Python. In v0.2 the lexer tokenises "{...}" as UpsiL, the
checker resolves the names (Python internals are not UpsiL names), and
runtime values are inserted verbatim.
"""

import unittest

from support import UpsilTestCase, compile_error, lang, run_upl

from upsil.compiler import compile_source

PAYLOAD = "{__import__('os').system('echo PWNED')}"


class InterpolationSafetyTest(UpsilTestCase):
    def test_python_code_in_braces_does_not_compile(self):
        with lang("en"):
            exc = compile_error('print("{__import__(\\"os\\")}")')
        self.assertIn("unexpected character", exc.format())
        with lang("en"):
            exc = compile_error('print("{__import__("os").getuid()}")')
        self.assertIn("undefined name '__import__'", exc.format())
        with lang("en"):
            exc = compile_error("print(\"{__import__('os')}\")")
        self.assertIn("double quotes", exc.format())

    def test_python_builtins_are_not_upsil_names(self):
        for name in ("eval", "exec", "open", "globals", "getattr", "compile", "__builtins__"):
            with self.subTest(name=name), lang("en"):
                exc = compile_error(f'print("{{{name}}}")')
                self.assertIn(f"undefined name '{name}'", exc.format())

    def test_braces_in_runtime_data_stay_literal(self):
        out = run_upl('val data = input()\nprint("got {data}")\nprint(data)\nprint(str(data) + "!")', stdin=PAYLOAD + "\n")
        self.assertEqual(out, f"got {PAYLOAD}\n{PAYLOAD}\n{PAYLOAD}!\n")
        self.assertNotIn("\nPWNED", out)

    def test_braces_in_data_reach_a_model_verbatim(self):
        src = ('class Spy {\n  var seen = []\n  fun ask(text, system = null, json = false) {\n'
               '    seen.append(text)\n    return "ok"\n  }\n}\n'
               'val m = Spy()\nval doc = input()\nval r = [m] => "Summarize {doc} {1 + 1}"\nprint(m.seen[0])')
        self.assertEqual(run_upl(src, stdin=PAYLOAD + "\n"), f"Summarize {PAYLOAD} 2\n")

    def test_quotes_and_backslashes_cannot_break_out(self):
        # the v0.1 injection: a quote inside a string closed the generated Python string
        src = r'print("hello\"); import os; print(\"uid")'
        self.assertEqual(run_upl(src), 'hello"); import os; print("uid\n')
        with lang("en"):
            exc = compile_error(r'print("hello\x22); import os")')
        self.assertIn("unknown escape '\\x'", exc.format())

    def test_escaped_braces_and_lone_brace(self):
        self.assertEqual(run_upl(r'print("\{__import__\} and }")'), "{__import__} and }\n")

    def test_generated_python_has_no_eval(self):
        src = 'val name = input()\nprint("Hi {name}! {[1, 2]}")\nval t = "{name:>10}"'
        text = compile_source(src, "s.upl").python_source()
        for bad in ("eval(", "exec(", ".format(", "compile("):
            self.assertNotIn(bad, text)


if __name__ == "__main__":
    unittest.main()
