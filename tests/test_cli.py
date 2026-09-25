# SPDX-License-Identifier: Apache-2.0
import os
import subprocess
import sys
import tempfile
import unittest

from mock_openai import free_port
from support import UpsilTestCase, clean_env, run_cli

FAIL = "fun main() {\n    val x = 0\n    print(\"before\")\n    print(1 / x)\n}\nmain()\n"
BAD = "val a = 1\nprint(a + )\n"


class CliTestCase(UpsilTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path


class RunTest(CliTestCase):
    def test_run_ok(self):
        path = self.write("hello.upl", 'print("Привет, UpsiL")\n')
        r = run_cli(["run", path])
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "Привет, UpsiL\n", ""))

    def test_file_shortcut_and_args(self):
        path = self.write("args.upl", "import sys\nprint(sys.args, len(sys.args))\n")
        r = run_cli([path, "a", "--flag"])
        self.assertEqual((r.returncode, r.stdout), (0, '["a", "--flag"] 2\n'))

    def test_program_from_stdin(self):
        r = run_cli(["run", "-"], stdin='print(6 * 7)\n')
        self.assertEqual((r.returncode, r.stdout), (0, "42\n"))

    def test_exit_code_from_sys_exit(self):
        path = self.write("exit.upl", 'import sys\nprint("bye")\nsys.exit(3)\nprint("never")\n')
        r = run_cli(["run", path])
        self.assertEqual((r.returncode, r.stdout), (3, "bye\n"))

    def test_python_modules_next_to_the_script(self):
        self.write("helper.py", "def twice(x):\n    return 2 * x\n")
        path = self.write("main.upl", 'import py "helper"\nprint(helper.twice(21))\n')
        r = run_cli(["run", path], cwd="/")
        self.assertEqual((r.returncode, r.stdout), (0, "42\n"))


class RuntimeErrorTest(CliTestCase):
    def test_friendly_traceback_in_english(self):
        path = self.write("fail.upl", FAIL)
        r = run_cli(["run", path])
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "before\n")
        self.assertIn("Runtime error (most recent call last):", r.stderr)
        self.assertIn(f"{path}:6, in <program>\n    main()\n", r.stderr)
        self.assertIn(f"{path}:4, in main\n    print(1 / x)\n", r.stderr)
        if sys.version_info >= (3, 11):
            self.assertIn("    print(1 / x)\n          ^^^^^\n", r.stderr)
        self.assertTrue(r.stderr.rstrip().endswith("ZeroDivisionError: division by zero"))
        self.assertNotIn("upsil/cli.py", r.stderr)

    def test_friendly_traceback_in_russian(self):
        path = self.write("fail.upl", FAIL)
        r = run_cli(["run", path], extra_env={"LANG": "ru_RU.UTF-8"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("Ошибка выполнения (последний вызов — внизу):", r.stderr)
        self.assertIn(":4, в main", r.stderr)
        self.assertIn("ZeroDivisionError: division by zero — деление на ноль", r.stderr)

    def test_upsil_errors_are_shown_as_messages(self):
        path = self.write("err.upl", 'fun check(n) {\n  if n < 0 { error("n must be >= 0, got {n}") }\n}\ncheck(-1)\n')
        r = run_cli(["run", path])
        self.assertEqual(r.returncode, 1)
        self.assertIn(":2, in check", r.stderr)
        self.assertTrue(r.stderr.rstrip().endswith("error: n must be >= 0, got -1"))

    def test_model_server_down(self):
        path = self.write("chat.upl", 'import llm\nllm m\nprint([m] => "hi")\n')
        port = free_port()
        r = run_cli(["run", path], extra_env={"LANG": "ru_RU.UTF-8", "UPSIL_LLM_URL": f"http://127.0.0.1:{port}/v1",
                                              "UPSIL_LLM_MODEL": "x"})
        self.assertEqual(r.returncode, 1)
        self.assertIn(":3, в <программа>\n    print([m] => \"hi\")", r.stderr)
        self.assertTrue(r.stderr.rstrip().endswith(
            f"ошибка: Локальная модель не отвечает (127.0.0.1:{port}). В СОС: sos models serve"))

    def test_deep_recursion_is_summarized(self):
        path = self.write("rec.upl", "fun down(n) {\n    return down(n + 1)\n}\ndown(0)\n")
        r = run_cli(["run", path])
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stderr, r"\[the same call repeated \d+ more times\]")
        self.assertLess(len(r.stderr.splitlines()), 30)
        self.assertTrue(r.stderr.rstrip().endswith("RecursionError: maximum recursion depth exceeded"))
        r = run_cli(["run", path], extra_env={"LANG": "ru_RU.UTF-8"})
        self.assertIn("— слишком глубокая рекурсия", r.stderr)

    def test_python_traceback_on_request(self):
        path = self.write("fail.upl", FAIL)
        r = run_cli(["run", path], extra_env={"UPSIL_TRACEBACK": "python"})
        self.assertIn("Traceback (most recent call last):", r.stderr)


class CompileErrorTest(CliTestCase):
    def test_compile_error_english(self):
        path = self.write("bad.upl", BAD)
        r = run_cli(["run", path])
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertEqual(r.stderr, f"{path}:2:11: error: unexpected ')' — expected an expression\n"
                                   f"  2 | print(a + )\n    |           ^\n")

    def test_compile_error_russian(self):
        path = self.write("bad.upl", BAD)
        r = run_cli(["run", path], extra_env={"LANG": "ru_RU.UTF-8"})
        self.assertEqual(r.returncode, 2)
        self.assertIn(f"{path}:2:11: ошибка: неожиданный токен ')' — ожидалось выражение", r.stderr)

    def test_language_detection_order(self):
        from upsil.i18n import detect_lang
        self.assertEqual(detect_lang({"LANG": "ru_RU.UTF-8"}), "ru")
        self.assertEqual(detect_lang({"LANG": "de_DE.UTF-8"}), "en")
        self.assertEqual(detect_lang({"LC_ALL": "en_US.UTF-8", "LANG": "ru_RU.UTF-8"}), "en")
        self.assertEqual(detect_lang({"LC_MESSAGES": "ru_RU.UTF-8", "LANG": "en_US.UTF-8"}), "ru")
        self.assertEqual(detect_lang({"UPSIL_LANG": "en", "LC_ALL": "ru_RU.UTF-8"}), "en")
        self.assertEqual(detect_lang({"LANGUAGE": "ru:en"}), "ru")
        self.assertEqual(detect_lang({}), "en")

    def test_upsil_lang_wins(self):
        path = self.write("bad.upl", BAD)
        r = run_cli(["run", path], extra_env={"LANG": "ru_RU.UTF-8", "UPSIL_LANG": "en"})
        self.assertIn("error: unexpected ')'", r.stderr)

    def test_several_semantic_errors(self):
        path = self.write("sem.upl", "val x = 1\nx = 2\nprint(y)\n")
        r = run_cli(["run", path])
        self.assertEqual(r.returncode, 2)
        self.assertIn(":2:1: error: cannot reassign val 'x'", r.stderr)
        self.assertIn(":3:7: error: undefined name 'y'", r.stderr)


class BuildTest(CliTestCase):
    def test_build_to_stdout_and_file(self):
        src = self.write("fib.upl", "fun fib(n) {\n  if n < 2 { return n }\n  return fib(n - 1) + fib(n - 2)\n}\n"
                                    "for (i in 0..10) { print(fib(i), end = \" \") }\nprint()\n")
        r = run_cli(["build", src])
        self.assertEqual(r.returncode, 0)
        self.assertIn("def fib(n):", r.stdout)
        out = os.path.join(self.tmp.name, "fib.py")
        r2 = run_cli(["build", src, "-o", out])
        self.assertEqual((r2.returncode, r2.stdout), (0, ""))
        with open(out, encoding="utf-8") as f:
            self.assertEqual(f.read(), r.stdout)
        ran = subprocess.run([sys.executable, out], capture_output=True, text=True, env=clean_env())
        self.assertEqual(ran.stdout, "0 1 1 2 3 5 8 13 21 34 \n")
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "fib.upl.py")))

    def test_build_never_overwrites_the_source(self):
        src = self.write("x.upl", "print(1)\n")
        r = run_cli(["build", src, "-o", src])
        self.assertEqual(r.returncode, 64)
        with open(src, encoding="utf-8") as f:
            self.assertEqual(f.read(), "print(1)\n")

    def test_build_compile_error(self):
        r = run_cli(["build", self.write("bad.upl", BAD)])
        self.assertEqual((r.returncode, r.stdout), (2, ""))


class CheckTest(CliTestCase):
    def test_check(self):
        good = self.write("good.upl", "val x: int = 1\nprint(x)\n")
        typed = self.write("typed.upl", 'val x: int = "one"\n')
        r = run_cli(["check", good])
        self.assertEqual((r.returncode, r.stdout), (0, f"{good}: ok\n"))
        r = run_cli(["check", good, typed])
        self.assertEqual(r.returncode, 2)
        self.assertIn(f"{good}: ok", r.stdout)
        self.assertIn("type mismatch: 'x' is declared as int but the value is a string", r.stderr)
        r = run_cli(["check", good], extra_env={"LANG": "ru_RU.UTF-8"})
        self.assertEqual(r.stdout, f"{good}: ошибок нет\n")
        r = run_cli(["check", good, os.path.join(self.tmp.name, "missing.upl")])
        self.assertEqual(r.returncode, 64)


class UsageTest(CliTestCase):
    def test_exit_codes_for_usage_errors(self):
        for args in ([], ["run"], ["frobnicate"], ["run", "/nonexistent/x.upl"], ["build"],
                     ["build", "a.upl", "b.upl"], ["build", "a.upl", "-o"], ["build", "--bogus", "a.upl"], ["check"]):
            with self.subTest(args=args):
                self.assertEqual(run_cli(args).returncode, 64)

    def test_folder_is_not_a_file(self):
        r = run_cli(["run", self.tmp.name])
        self.assertEqual(r.returncode, 64)
        self.assertIn("this is a folder, not a file", r.stderr)

    def test_help_and_version(self):
        r = run_cli(["--help"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("Usage:", r.stdout)
        self.assertIn("Exit codes: 0 success, 1 run-time error, 2 compile error, 64 usage error.", r.stdout)
        r = run_cli(["help"], extra_env={"LANG": "ru_RU.UTF-8"})
        self.assertIn("Использование:", r.stdout)
        self.assertIn("в СОС: sos models serve", r.stdout)
        r = run_cli([])
        self.assertEqual(r.returncode, 64)
        self.assertIn("Usage:", r.stderr)
        r = run_cli(["version"])
        self.assertEqual(r.returncode, 0)
        self.assertTrue(r.stdout.startswith("UpsiL 0.2.0 (Python "))


if __name__ == "__main__":
    unittest.main()
