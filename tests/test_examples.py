# SPDX-License-Identifier: Apache-2.0
"""Every example compiles; the offline ones match golden output; the AI ones
run against the mock OpenAI server; neural_net runs when PyTorch is there."""

import contextlib
import importlib.util
import json
import os
import re
import time
import unittest

from fake_modules import fake_tkinter, modules
from mock_openai import MockOpenAI
from support import EXAMPLES, ROOT, UpsilTestCase, env, run_cli

from upsil.compiler import check_source, compile_source

GOLDEN = ROOT / "tests" / "golden"
HAS_TORCH = importlib.util.find_spec("torch") is not None
HAS_NUMPY = importlib.util.find_spec("numpy") is not None


class ExamplesTest(UpsilTestCase):
    def test_every_example_passes_upsil_check(self):
        files = sorted(EXAMPLES.glob("*.upl"))
        self.assertGreaterEqual(len(files), 8)
        for path in files:
            with self.subTest(example=path.name):
                check_source(path.read_text(encoding="utf-8"), str(path), lint_types=True)

    def test_golden_outputs(self):
        for name in ("hello", "fib", "collections", "logs"):
            with self.subTest(example=name):
                r = run_cli(["run", f"examples/{name}.upl"])
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout, (GOLDEN / f"{name}.out").read_text(encoding="utf-8"))


def run_cli_script(args, extra_env=None):
    import subprocess
    import sys
    from support import clean_env
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, encoding="utf-8",
                          env=clean_env(extra_env), cwd=str(ROOT), timeout=600)


def review_reply(body):
    """Sentiment by keywords, like a small model; the second review gets prose once."""
    text = body["messages"][-1]["content"]
    if "Ужасная" in text and len(body["messages"]) == 2:
        return "Хм, это скорее негатив."
    if "Оцени тональность" not in text and "JSON" in text:
        return json.dumps({"label": "neg", "score": 0.9})
    for words, label, score in ((("Отличный", "Супер"), "pos", 0.9), (("Ужасная", "сломался"), "neg", 0.8)):
        if any(w in text for w in words):
            return json.dumps({"label": label, "score": score})
    return json.dumps({"label": "neu", "score": 0.5})


class AIExamplesTest(UpsilTestCase):
    def run_example(self, mock, args, stdin=None):
        return run_cli(["run", *args], extra_env={"UPSIL_LLM_URL": mock.url}, stdin=stdin)

    def test_chat(self):
        with MockOpenAI() as mock:
            r = self.run_example(mock, ["examples/chat.upl"], stdin="привет\nкак дела?\n")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, "Чат с моделью. Пустая строка или Ctrl-D — выход.\n"
                                       "> echo: привет\n> echo: как дела?\n> ")
            sizes = [len(q["body"]["messages"]) for q in mock.chat_requests()]
            self.assertEqual(sizes, [2, 4])      # the history grows: system, user, assistant, user
            self.assertTrue(all(q["body"]["stream"] for q in mock.chat_requests()))

    def test_rag_notes_with_embeddings(self):
        with MockOpenAI() as mock:
            r = self.run_example(mock, ["examples/rag_notes.upl", "examples/notes", "Как проверить резервную копию?"])
            self.assertEqual(r.returncode, 0, r.stderr)
            lines = r.stdout.splitlines()
            self.assertEqual(lines[0], "Фрагментов в индексе: 3 (папка examples/notes, поиск: embeddings)")
            self.assertEqual(lines[1], "echo: Заметки:")
            self.assertEqual(lines[2], "[backup.md]")          # the best match comes first
            self.assertIn("Вопрос: Как проверить резервную копию?", r.stdout)
            system = mock.chat_requests()[0]["body"]["messages"][0]["content"]
            self.assertIn("Отвечай только по заметкам", system)
            self.assertEqual(r.stderr, "")

    def test_rag_notes_without_embeddings(self):
        with MockOpenAI(embeddings=False) as mock:
            r = self.run_example(mock, ["examples/rag_notes.upl", "examples/notes", "Как проверить резервную копию?"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("поиск: bm25", r.stdout)
            self.assertIn("[backup.md]", r.stdout)
            self.assertNotIn("[recipes/tea.md]", r.stdout)     # BM25 returns only matching notes
            self.assertIn("searching by words (BM25)", r.stderr)

    def test_rag_notes_interactive(self):
        with MockOpenAI(embeddings=False) as mock:
            r = self.run_example(mock, ["examples/rag_notes.upl"], stdin="чабрец\n\n")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("[recipes/tea.md]", r.stdout)

    def test_reviews(self):
        import tempfile
        with MockOpenAI(reply=review_reply) as mock, tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "labeled.csv")
            r = self.run_example(mock, ["examples/reviews.upl", "examples/data/reviews.csv", out])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, f"размечено 6 из 6, записано в {out}\n"
                                       "позитивных 2, негативных 2, нейтральных 2\n")
            with open(out, encoding="utf-8") as f:
                rows = f.read().splitlines()
            self.assertEqual(rows[0], "text,label,score")
            self.assertTrue(rows[1].endswith(",pos,0.9"), rows)          # sorted by score
            shapes = [q["body"].get("response_format", {}).get("type") for q in mock.chat_requests()]
            self.assertEqual(set(shapes), {"json_schema"})
            self.assertEqual(len(shapes), 7)                               # one answer was asked again

    def test_triage(self):
        def decide(body):
            text = body["messages"][-1]["content"]
            state, _, question = text.partition("\n\nQuestion: ")
            if question.startswith("Какой отдел"):
                for word, letter in (("деньги", "A"), ("войти", "B"), ("упало", "B"), ("тариф", "C")):
                    if word in state:
                        return {letter: 0.9, "A" if letter != "A" else "C": 0.1}
                return {"A": 0.4, "B": 0.35, "C": 0.25}           # not sure: a human decides
            if question.startswith("Нужно ответить"):
                return {"A": 0.9, "B": 0.1} if "!" in state or "упало" in state else {"A": 0.3, "B": 0.7}
            return {"C": 0.8, "A": 0.2} if "!" in state else {"B": 0.6, "A": 0.4}
        with MockOpenAI(decide=decide) as mock:
            r = self.run_example(mock, ["examples/triage.upl", "examples/data/tickets.csv"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.splitlines(), [
                "billing (90%) · в порядке очереди · клиент недоволен",
                "  Списали деньги дважды за один месяц, верните, пожалуйста",
                "tech (90%) · сегодня · клиент зол",
                "  Не могу войти в аккаунт, пишет «ошибка 500». Всё стоит, клиенты ждут!",
                "sales (90%) · в порядке очереди · клиент недоволен",
                "  Сколько стоит тариф для команды из десяти человек?",
                "tech (90%) · сегодня · клиент недоволен",
                "  Приложение опять упало при загрузке файла, это уже третий раз",
                "человеку: 1",
                "  ? Здравствуйте, у меня вопрос",
            ])
            self.assertEqual(len(mock.chat_requests()), 15)                # 5 tickets × 3 questions

    def test_prompt_eval(self):
        def reply(body):
            text = body["messages"][-1]["content"]
            if "Франции" in text:
                return "Париж"
            if "2 + 2" in text:
                return "4" if "эрудит" not in text else "четыре"
            return "Голубое" if "кратко" in text else "синее"
        with MockOpenAI(reply=reply) as mock:
            r = self.run_example(mock, ["examples/prompt_eval.upl"])
            self.assertEqual(r.returncode, 0, r.stderr)
            lines = [re.sub(r"\d+\.\d с$", "N с", line) for line in r.stdout.splitlines()]
            self.assertEqual(lines, ["вежливо    3/3  N с", "коротко    2/3  N с", "эрудит     1/3  N с"])

    def test_summarize(self):
        def reply(body):
            system = body["messages"][0]["content"]
            if "JSON" in system:
                return json.dumps({"keywords": ["модели", "данные", "задачи"]}, ensure_ascii=False)
            return "1. Модели стали меньше.\n2. Данные остаются дома.\n3. Подходят для проверяемых задач."

        with MockOpenAI(reply=reply) as mock:
            r = self.run_example(mock, ["examples/summarize.upl", "examples/sample.txt", "3"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.startswith("Файл: examples/sample.txt, символов: "))
            self.assertIn("2. Данные остаются дома.", r.stdout)
            self.assertTrue(r.stdout.endswith("Ключевые слова: модели, данные, задачи\n"))
            first = mock.chat_requests()[0]["body"]["messages"]
            self.assertTrue(first[1]["content"].startswith("Перескажи текст в 3 пунктах"))
            self.assertIn("Локальные языковые модели", first[1]["content"])
            self.assertEqual(mock.chat_requests()[1]["body"]["response_format"], {"type": "json_object"})
            r = self.run_example(mock, ["examples/summarize.upl"])
            self.assertEqual(r.returncode, 64)

    def test_neurochat_with_a_stand_in_window(self):
        with MockOpenAI() as mock, env(UPSIL_LLM_URL=mock.url, UPSIL_CONFIG=os.devnull, UPSIL_LLM_MODEL=None,
                                       UPSIL_LANG="en"), modules(**fake_tkinter()):
            path = EXAMPLES / "neurochat.upl"
            namespace = {"__name__": "__main__"}
            exec(compile_source(path.read_text(encoding="utf-8"), str(path)).code, namespace)
            window = namespace["window"]
            self.assertIn("Напишите сообщение", window.history.text)
            window.entry.value = "привет"
            window._on_send()
            deadline = time.monotonic() + 5
            while "Модель: echo: привет" not in window.history.text and time.monotonic() < deadline:
                time.sleep(0.01)
                window._poll()
            self.assertIn("You: привет", window.history.text)
            self.assertIn("Модель: echo: привет", window.history.text)
            self.assertEqual(len(namespace["history"]), 3)

    @unittest.skipUnless(HAS_TORCH, "PyTorch is not installed")
    def test_neural_net(self):
        r = run_cli(["run", "examples/neural_net.upl"], timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr)
        answers = re.findall(r"^(\d) XOR (\d) ≈ ([0-9.]+)$", r.stdout, re.M)
        self.assertEqual(len(answers), 4, r.stdout)
        for a, b, p in answers:
            self.assertEqual(round(float(p)), int(a) ^ int(b), r.stdout)

    @unittest.skipUnless(HAS_NUMPY, "microtorch needs numpy (CI installs it)")
    def test_neural_examples_on_microtorch(self):
        # tests/microtorch.py stands in for PyTorch: the examples really train
        for name, check in (("neural_net", r"^1 XOR 0 ≈ 1\.00$"), ("spirals", r"^точность на отложенных точках: 100%$")):
            with self.subTest(example=name):
                r = run_cli_script(["tests/run_microtorch.py", f"examples/{name}.upl"])
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertRegex(r.stdout, re.compile(check, re.M))

    def test_neural_net_without_torch(self):
        if HAS_TORCH:
            self.skipTest("PyTorch is installed")
        r = run_cli(["run", "examples/neural_net.upl"], extra_env={"LANG": "ru_RU.UTF-8"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("examples/neural_net.upl:6, в <программа>", r.stderr)
        self.assertIn("ошибка: PyTorch не установлен", r.stderr)


if __name__ == "__main__":
    unittest.main()
