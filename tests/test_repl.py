# SPDX-License-Identifier: Apache-2.0
import unittest

from support import UpsilTestCase, run_cli


class ReplTest(UpsilTestCase):
    def repl(self, text, **kwargs):
        return run_cli(["repl"], stdin=text, **kwargs)

    def test_values_are_echoed(self):
        r = self.repl('val x = 21\nx * 2\n"hi"\n[1, null, true]\nprint("printed")\nnull\n')
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, '42\n"hi"\n[1, null, true]\nprinted\n', ""))

    def test_multiline_input(self):
        r = self.repl('fun greet(name) {\n    return "Hi, {name}!"\n}\ngreet("UpsiL")\nval total = 1 +\n  2\ntotal\n')
        self.assertEqual(r.stdout, '"Hi, UpsiL!"\n3\n')

    def test_errors_do_not_end_the_session(self):
        r = self.repl("print(nope)\n1 / 0\nval ok = 1\nok\n")
        self.assertEqual((r.returncode, r.stdout), (0, "1\n"))
        self.assertIn("undefined name 'nope'", r.stderr)
        self.assertIn("ZeroDivisionError: division by zero", r.stderr)

    def test_failed_input_declares_nothing(self):
        r = self.repl("val a = nope\nval a = 5\na\n")
        self.assertEqual(r.stdout, "5\n")

    def test_names_can_be_declared_again(self):
        r = self.repl("val x = 1\nval x = x + 1\nx\nfun f() { return x }\nf()\n")
        self.assertEqual(r.stdout, "2\n2\n")

    def test_quit(self):
        r = self.repl("1\n:q\n2\n")
        self.assertEqual((r.returncode, r.stdout), (0, "1\n"))

    def test_unfinished_input_at_the_end(self):
        r = self.repl("fun f() {\n  return 1\n")
        self.assertEqual(r.returncode, 0)
        self.assertIn("'{' is never closed", r.stderr)


if __name__ == "__main__":
    unittest.main()
