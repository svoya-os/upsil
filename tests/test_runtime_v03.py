# SPDX-License-Identifier: Apache-2.0
"""UpsiL 0.3 runtime: JSON shapes and retries, ask_all, nn helpers (on microtorch), csv, re,
and the `upsil test` runner."""

import importlib.util
import json
import os
import sys
import tempfile
import textwrap
import unittest

from mock_openai import MockOpenAI
from support import UpsilTestCase, lang, run_cli, run_upl

from upsil.runtime import llm


class ShapesTest(UpsilTestCase):
    SHAPE = {"label": ["pos", "neg", "neu"], "score": float, "tags?": [str]}

    def test_describe_and_json_schema(self):
        self.assertEqual(llm.describe_shape(self.SHAPE),
                         '{"label": "pos" | "neg" | "neu", "score": number, "tags"?: [string, ...]}')
        self.assertEqual(llm.json_schema(self.SHAPE), {
            "type": "object", "required": ["label", "score"],
            "properties": {"label": {"enum": ["pos", "neg", "neu"]}, "score": {"type": "number"},
                           "tags": {"type": "array", "items": {"type": "string"}}}})

    def test_conform(self):
        self.assertEqual(llm.conform({"label": "pos", "score": 1}, self.SHAPE), {"label": "pos", "score": 1.0})
        self.assertEqual(llm.conform({"n": 3.0}, {"n": int}), {"n": 3})
        self.assertEqual(llm.conform([{"a": "x"}], [{"a": str}]), [{"a": "x"}])
        with lang("en"):
            for value, shape, message in (
                    ({"label": "good", "score": 1}, self.SHAPE, "'label': expected one of \"pos\", \"neg\", \"neu\""),
                    ({"label": "pos"}, self.SHAPE, "'score' is missing"),
                    ({"n": 2.5}, {"n": int}, "'n': expected an integer, got the number 2.5"),
                    ({"xs": [1, "a"]}, {"xs": [int]}, "'xs[1]': expected an integer"),
                    ({"flag": 1}, {"flag": bool}, "'flag': expected true or false"),
                    ("text", dict, "the answer: expected an object")):
                with self.subTest(message=message):
                    with self.assertRaises(llm.FormatError) as ctx:
                        llm.conform(value, shape)
                    self.assertIn(message, str(ctx.exception))

    def test_bad_shape(self):
        with lang("en"), self.assertRaises(Exception) as ctx:
            llm.Model(url="http://127.0.0.1:9/v1").ask("x", schema={"a": 5})
        self.assertIn("is not a JSON shape", str(ctx.exception))

    def test_retry_with_what_was_wrong(self):
        replies = iter(["Конечно! Позитивный.", json.dumps({"label": "good", "score": 0.9}),
                        json.dumps({"label": "pos", "score": 1})])
        with MockOpenAI(reply=lambda body: next(replies)) as mock:
            m = llm.Model(url=mock.url, json_retries=2)
            self.assertEqual(m.ask("оцени", schema=self.SHAPE), {"label": "pos", "score": 1.0})
            requests = mock.chat_requests()
            self.assertEqual(len(requests), 3)
            self.assertEqual(requests[0]["body"]["response_format"]["type"], "json_schema")
            self.assertIn('Shape: {"label": "pos" | "neg" | "neu"', requests[0]["body"]["messages"][0]["content"])
            last = requests[2]["body"]["messages"]
            self.assertEqual(last[-2], {"role": "assistant", "content": '{"label": "good", "score": 0.9}'})
            self.assertIn("expected one of", last[-1]["content"])

    def test_no_retries_left(self):
        with MockOpenAI(reply=lambda body: "не JSON") as mock:
            with self.assertRaises(llm.FormatError) as ctx:
                llm.Model(url=mock.url).ask("x", json=True)
            self.assertEqual(ctx.exception.reply, "не JSON")
            self.assertEqual(len(mock.chat_requests()), 2)          # one retry by default

    def test_servers_without_json_schema(self):
        with MockOpenAI(json_mode=False, reply=lambda body: '{"a": 1}') as mock:
            m = llm.Model(url=mock.url)
            self.assertEqual(m.ask("x", schema={"a": int}), {"a": 1})
            self.assertEqual(m.ask("x", schema={"a": int}), {"a": 1})
            kinds = [r["body"].get("response_format", {}).get("type") for r in mock.chat_requests()]
            # json_schema refused -> json_object refused -> words only, remembered for the next call
            self.assertEqual(kinds[-1], None)

    def test_prompt_operator_with_a_shape(self):
        with MockOpenAI(reply=lambda body: '{"name": "Аня", "age": 30}') as mock:
            out = run_upl(f'import llm\nllm m = llm.Model(url = "{mock.url}")\n'
                          'val p = [m] => "Аня, 30 лет" -> json({"name": str, "age": int})\n'
                          'print(p["name"], p["age"] + 1)')
            self.assertEqual(out, "Аня 31\n")

    def test_catching_a_format_error(self):
        with MockOpenAI(reply=lambda body: "увы") as mock:
            out = run_upl(f'import llm\nllm m = llm.Model(url = "{mock.url}", json_retries = 0)\n'
                          'try { print([m] => "x" -> json) } catch (e: llm.FormatError) { print("формат:", e.reply) }')
            self.assertEqual(out, "формат: увы\n")

    def test_ask_all_keeps_order_and_can_skip_failures(self):
        def reply(body):
            text = body["messages"][-1]["content"]
            return "плохо" if text == "b" else json.dumps({"echo": text})
        with MockOpenAI(reply=reply) as mock:
            m = llm.Model(url=mock.url, json_retries=0)
            self.assertEqual(m.ask_all(["a", "b", "c"], schema={"echo": str}, errors="null", workers=3),
                             [{"echo": "a"}, None, {"echo": "c"}])
            with self.assertRaises(llm.FormatError):
                m.ask_all(["a", "b"], json=True)
            self.assertEqual(llm.Model(url=mock.url).ask_all([]), [])


HAS_NUMPY = importlib.util.find_spec("numpy") is not None


@unittest.skipUnless(HAS_NUMPY, "microtorch needs numpy (CI installs it)")
class NNHelpersTest(UpsilTestCase):
    def setUp(self):
        import microtorch
        self.undo = microtorch.install()
        from upsil.runtime import nn
        self.saved = nn._torch
        nn._torch = None

    def tearDown(self):
        from upsil.runtime import nn
        nn._torch = self.saved
        self.undo()

    def test_fit_batches_evaluating_accuracy(self):
        out = run_upl(textwrap.dedent('''\
            import nn
            nn.manual_seed(0)
            val x = nn.tensor([[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]])
            val y = nn.tensor([0, 1, 1, 0])
            model Net {
                val l1 = nn.Linear(2, 16)
                val l2 = nn.Linear(16, 2)
                graph forward(x) { return l2(nn.tanh(l1(x))) }
            }
            val net = Net()
            print(nn.count_params(net), nn.auto_device())
            val history = nn.fit(net, x, y, epochs = 150, lr = 0.05, batch = 4, val = (x, y), every = 50)
            print(len(history), history[-1]["val_accuracy"], nn.accuracy(net, x, y))
            print([len(b) for b in nn.batches(x, size = 3)])
            with nn.evaluating(net) {
                print(net.training, nn.torch.is_grad_enabled())
            }
            print(net.training)
            '''))
        lines = out.splitlines()
        self.assertEqual(lines[0], "82 cpu")
        self.assertTrue(lines[1].startswith("epoch  50/150 · loss "), lines[1])
        self.assertIn("· accuracy", lines[3])
        self.assertEqual(lines[4], "150 1.0 1.0")
        self.assertEqual(lines[5], "[3, 1]")
        self.assertEqual(lines[6], "false false")
        self.assertEqual(lines[7], "false")         # fit leaves the model in evaluation mode

    def test_batches_check_lengths(self):
        with lang("en"):
            with self.assertRaises(Exception) as ctx:
                run_upl("import nn\nfor (b in nn.batches(nn.tensor([1, 2]), nn.tensor([1]))) { print(b) }")
            self.assertIn("the tensors differ in length", str(ctx.exception))

    def test_regression_uses_mse(self):
        out = run_upl(textwrap.dedent('''\
            import nn
            nn.manual_seed(1)
            val x = nn.tensor([[i / 10] for i in 0..20])
            val y = x * 3.0 + 1.0
            val net = nn.Linear(1, 1)
            val h = nn.fit(net, x, y, epochs = 300, lr = 0.05, batch = 8, quiet = true)
            print(h[-1]["loss"] < 0.01, round(net.weight.item(), 1), round(net.bias.item(), 1))
            '''))
        self.assertEqual(out, "true 3.0 1.0\n")


class RecordsTest(UpsilTestCase):
    def test_json_csv_and_answers_are_records(self):
        self.assertRuns(textwrap.dedent('''\
            import json
            val d = json.parse(r"""{"name": "Аня", "tags": [{"k": 1}], "items": 3}""")
            d.age = 30
            print(d.name, d.tags[0].k, d["items"], d.age, d == {"name": "Аня", "tags": [{"k": 1}], "items": 3, "age": 30})
            print(json.stringify(d))
            '''), 'Аня 1 3 30 true\n{"name": "Аня", "tags": [{"k": 1}], "items": 3, "age": 30}\n')
        with lang("en"), self.assertRaises(AttributeError) as ctx:
            run_upl('import json\nprint(json.parse("\\{\\"a\\": 1\\}").b)')
        self.assertIn("no field 'b' (fields: a)", str(ctx.exception))
        with MockOpenAI(reply=lambda body: '{"plan": {"steps": [{"tool": "calc"}]}}') as mock:
            out = run_upl(f'import llm\nllm m = llm.Model(url = "{mock.url}")\n'
                          'val a = [m] => "x" -> json\nprint(a.plan.steps[0].tool)')
            self.assertEqual(out, "calc\n")


class CsvReTest(UpsilTestCase):
    def test_csv_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.csv")
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write('text,stars\nхорошо,5\n"плохо, очень",1\nсредне,4.5\n')
            out = run_upl(textwrap.dedent(f'''\
                import csv
                val rows = csv.read("{path}", numbers = true)
                print(rows)
                print(csv.read("{path}", header = false)[0])
                print(csv.write("{path}.out", [{{"a": 1, "b": true}}, {{"a": 2, "c": null}}]))
                print(csv.stringify([[1, "x,y"]], columns = ["n", "s"]))
                '''))
            self.assertEqual(out, '[{"text": "хорошо", "stars": 5}, {"text": "плохо, очень", "stars": 1}, '
                                  '{"text": "средне", "stars": 4.5}]\n["text", "stars"]\n2\nn,s\n1,"x,y"\n\n')
            with open(path + ".out", encoding="utf-8") as f:
                self.assertEqual(f.read(), "a,b,c\n1,true,\n2,,\n")

    def test_re(self):
        out = run_upl(textwrap.dedent(r'''
            import re
            print(re.test(r"\d{4}", "в 2026 году"), re.find(r"\d+", "цена 450"), re.find(r"x", "abc"))
            print(re.find_all(r"#(\w+)", "#ии #сос"), re.find_all(r"(\w)(\d)", "a1 b2"), re.find_all(r"\d", "1a2"))
            print(re.groups(r"(\w+)@(\w+)", "max@sos"), re.groups(r"z", "a"))
            print(re.replace(r"\s+", " ", "а    б"), re.replace(r"\d+", m => int(m) * 2, "3 и 4"))
            print(re.split(r"[,;]\s*", "a, b;c"), re.test("ПРИВЕТ", "привет", ignore_case = true), re.escape("a.b"))
            '''))
        self.assertEqual(out, 'true 450 null\n["ии", "сос"] [["a", "1"], ["b", "2"]] ["1", "2"]\n'
                              '["max", "sos"] null\nа б 6 и 8\n["a", "b", "c"] true a\\.b\n')
        with lang("en"), self.assertRaises(Exception) as ctx:
            run_upl('import re\nprint(re.find(r"(", "x"))')
        self.assertIn("bad regular expression", str(ctx.exception))


class TestRunnerTest(UpsilTestCase):
    def test_upsil_test(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "tests"))
            with open(os.path.join(d, "text.upl"), "w", encoding="utf-8") as f:
                f.write('fun shout(s) { return s.upper() + "!" }\n')
            with open(os.path.join(d, "tests", "test_text.upl"), "w", encoding="utf-8") as f:
                f.write(textwrap.dedent('''\
                    import "../text.upl"
                    fun test_ok() { assert text.shout("а") == "А!" }
                    fun test_fails() {
                        assert text.shout("а") == "А", "лишний знак"
                    }
                    fun test_error() { print({"a": 1}["b"]) }
                    fun helper() { return 1 }
                    '''))
            with open(os.path.join(d, "tests", "notes.upl"), "w", encoding="utf-8") as f:
                f.write("fun test_ignored() { assert false }\n")
            r = run_cli(["test"], cwd=d)
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertEqual(r.stdout.splitlines()[:4], [
                os.path.join("tests", "test_text.upl"),
                "  ✓ test_ok",
                f"  ✗ test_fails — лишний знак  ({os.path.join('tests', 'test_text.upl')}:4)",
                f"  ✗ test_error — KeyError: 'b'  ({os.path.join('tests', 'test_text.upl')}:6)",
            ])
            self.assertTrue(r.stdout.splitlines()[-1].startswith("3 tests: 1 passed, 2 failed"))
            r = run_cli(["test", os.path.join("tests", "test_text.upl")], cwd=d, extra_env={"UPSIL_LANG": "ru"})
            self.assertIn("3 теста: 1 прошёл, 2 не прошли", r.stdout)
            with open(os.path.join(d, "tests", "test_text.upl"), "w", encoding="utf-8") as f:
                f.write("fun test_a() { assert 1 == 1 }\n")
            r = run_cli(["test"], cwd=d)
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertTrue(r.stdout.endswith("1 test: 1 passed, 0 failed (0.00 s)\n") or "1 test: 1 passed" in r.stdout)

    def test_no_tests(self):
        with tempfile.TemporaryDirectory() as d:
            r = run_cli(["test"], cwd=d)
            self.assertEqual(r.returncode, 64)
            self.assertIn("no test files", r.stdout)


if __name__ == "__main__":
    unittest.main()
