# SPDX-License-Identifier: Apache-2.0
import contextlib
import os
import sys
import tempfile
import time
import unittest

from fake_modules import fake_tkinter, modules
from mock_openai import MockOpenAI, free_port
from support import UpsilTestCase, env, lang, run_upl

from upsil.errors import UpsilError
from upsil.runtime import fs, http, json, random, ui
from upsil.runtime import sys as usys
from upsil.runtime import time as utime


class FsTest(UpsilTestCase):
    def test_files_from_upsil(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = (f'import fs\nval root = "{tmp}"\nfs.mkdir(fs.join(root, "notes", "sub"))\n'
                   'val p = fs.join(root, "notes", "a.md")\nfs.write(p, "# Title\\n")\nfs.append(p, "line 2\\n")\n'
                   'fs.write(fs.join(root, "notes", "sub", "b.md"), "b")\nfs.write(fs.join(root, "notes", "c.txt"), "c")\n'
                   'print(fs.read(p) == "# Title\\nline 2\\n", fs.lines(p), fs.exists(p), fs.is_file(p), fs.is_dir(root))\n'
                   'print(fs.list(fs.join(root, "notes")), fs.list(fs.join(root, "notes"), "**/*.md"))\n'
                   'fs.remove(p)\nprint(fs.exists(p))\n')
            self.assertEqual(run_upl(src.replace("\\", "\\\\") if os.sep == "\\" else src),
                             'true ["# Title", "line 2"] true true true\n'
                             '["a.md", "c.txt", "sub"] ["a.md", "sub/b.md"]\nfalse\n')

    def test_paths(self):
        self.assertEqual(fs.home(), os.path.expanduser("~"))
        self.assertEqual(fs.cwd(), os.getcwd())
        self.assertEqual((fs.dirname("a/b.md"), fs.basename("a/b.md"), fs.dirname("b.md")), ("a", "b.md", ""))


class JsonTest(UpsilTestCase):
    def test_json(self):
        self.assertRuns('import json\nval d = json.parse("\\{\\"a\\": [1, 2], \\"b\\": null\\}")\n'
                        'print(d["a"], d["b"], json.stringify({"x": true, "имя": "Макс"}))',
                        '[1, 2] null {"x": true, "имя": "Макс"}\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "d.json")
            json.write(path, {"k": [1]})
            self.assertEqual(json.read(path), {"k": [1]})
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), '{\n  "k": [\n    1\n  ]\n}\n')


class SysTest(UpsilTestCase):
    def test_args_env_exit(self):
        saved = sys.argv
        sys.argv = ["tool.upl", "a", "b"]
        try:
            with env(UPSIL_TEST_VAR="42"):
                self.assertRuns('import sys\nprint(sys.args, sys.script, sys.env("UPSIL_TEST_VAR"), sys.env("NOPE", "d"), '
                                'sys.version)', '["a", "b"] tool.upl 42 d 0.2.0\n')
        finally:
            sys.argv = saved
        with self.assertRaises(SystemExit) as cm:
            usys.exit(3)
        self.assertEqual(cm.exception.code, 3)
        self.assertEqual(usys.platform, sys.platform)


class SmallModulesTest(UpsilTestCase):
    def test_math(self):
        self.assertRuns("import math\nprint(math.sqrt(16), math.floor(2.7), round(math.pi, 2), math.gcd(12, 18))",
                        "4.0 2 3.14 6\n")

    def test_time(self):
        self.assertAlmostEqual(utime.now(), time.time(), delta=5)
        self.assertRegex(utime.today(), r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(utime.format("%Y", at=0)[:2], "19")
        t0 = utime.monotonic()
        utime.sleep(0.01)
        self.assertGreater(utime.monotonic(), t0)

    def test_random(self):
        self.assertRuns("import random\nrandom.seed(1)\nval a = random.randint(1, 6)\nrandom.seed(1)\n"
                        "print(a == random.randint(1, 6), random.choice([7]))\nval xs = [1, 2, 3]\nrandom.shuffle(xs)\n"
                        "print(sorted(xs), 0 <= random.random() and random.random() < 1)", "true 7\n[1, 2, 3] true\n")
        self.assertTrue(2 <= random.uniform(2, 3) <= 3)
        self.assertEqual(sorted(random.sample([1, 2, 3], 3)), [1, 2, 3])


class HttpTest(UpsilTestCase):
    def test_get_and_post(self):
        with MockOpenAI() as mock:
            self.assertIn('"mock-small"', http.get(mock.url + "/models"))
            self.assertEqual(http.get_json(mock.url + "/models")["data"][0]["id"], "mock-small")
            text = http.post(mock.url + "/chat/completions", "plain text", headers={"X-Test": "1"})
            self.assertIn('"chat.completion"', text)
            self.assertEqual(mock.requests[-1]["headers"]["Content-Type"], "text/plain; charset=utf-8")
            self.assertEqual(mock.requests[-1]["headers"]["X-Test"], "1")
            reply = http.post_json(mock.url + "/chat/completions", {"model": "m", "messages": [{"role": "user", "content": "q"}]})
            self.assertEqual(reply["choices"][0]["message"]["content"], "echo: q")
            with lang("en"), self.assertRaises(UpsilError) as cm:
                http.get(mock.url + "/missing")
            self.assertIn("HTTP 404 from", str(cm.exception))
            self.assertIn("no route /v1/missing", str(cm.exception))

    def test_unreachable(self):
        with lang("en"), self.assertRaises(UpsilError) as cm:
            http.get(f"http://127.0.0.1:{free_port()}/")
        self.assertIn("Cannot reach 127.0.0.1", str(cm.exception))


class UiTest(UpsilTestCase):
    def test_window_messages_and_background_handler(self):
        with modules(**fake_tkinter()), lang("en"):
            w = ui.Window("Chat", 300, 400)
            self.assertEqual((w.root.window_title, w.root.window_geometry), ("Chat", "300x400"))
            w.add_message("hello")
            self.assertIn("hello\n\n", w.history.text)

            def handler(text):
                if text == "boom":
                    raise ValueError("boom!")
                w.add_message("AI: " + text.upper())

            w.on_submit(handler)
            for text, expected in (("hi", "AI: HI"), ("boom", "error: boom!")):
                w.entry.value = text
                w._on_send()
                self.assertIn(f"You: {text}", w.history.text)
                self.assertTrue(w._busy)
                deadline = time.monotonic() + 5
                while expected not in w.history.text and time.monotonic() < deadline:
                    time.sleep(0.01)
                    w._poll()
                self.assertIn(expected, w.history.text)
                self.assertFalse(w._busy)
            w.close()
            self.assertTrue(w.root.destroyed)

    def test_no_display(self):
        with modules(**fake_tkinter(fail_display=True)), lang("en"), self.assertRaises(UpsilError) as cm:
            ui.Window()
        self.assertIn("No graphical display", str(cm.exception))

    def test_no_tkinter(self):
        with modules(tkinter=None), lang("ru"):
            with self.assertRaises(UpsilError) as cm:
                ui.Window()
            self.assertIn("tkinter не установлен: sudo apt install python3-tk", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
