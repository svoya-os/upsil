# SPDX-License-Identifier: Apache-2.0
"""UpsiL 0.4: decisions. `-> choice`, `-> yes`, `-> score`, m.decide(...) and llm.SystemOne."""

import contextlib
import os
import textwrap
import unittest

from mock_openai import MockOpenAI
from support import UpsilTestCase, env, run_upl

from upsil.errors import UpsilError
from upsil.runtime import llm


def letters(**probs):
    """decide callback: fixed probabilities of the first token."""
    return lambda body: dict(probs)


class DecisionCase(UpsilTestCase):
    def serve(self, **kw):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        mock = stack.enter_context(MockOpenAI(**kw))
        stack.enter_context(env(UPSIL_LLM_URL=mock.url, UPSIL_CONFIG=os.devnull, UPSIL_LLM_MODEL=None,
                                UPSIL_LLM_KEY=None, OPENAI_API_KEY=None, UPSIL_LANG="en"))
        return mock


class OperatorTest(DecisionCase):
    def test_choice_yes_and_score(self):
        answers = iter([{"B": 0.9, "A": 0.06, "C": 0.04},       # choice
                        {"A": 0.8, "B": 0.2},                    # yes
                        {"C": 0.6, "B": 0.3, "D": 0.1},          # score 0..=3
                        {" b": 0.5, "B.": 0.25, "A": 0.25}])     # tokens with spaces and dots
        mock = self.serve(decide=lambda body: next(answers))
        out = run_upl(textwrap.dedent('''\
            import llm
            llm m
            val ticket = "Не могу войти, пишет «ошибка 500»"
            val team = [m] => "Кто займётся обращением? {ticket}" -> choice(["billing", "tech", "sales"])
            print(team, team.value, team.p, team == "tech", team.probs["billing"])
            val urgent = [m] => "Нужен ответ сегодня? {ticket}" -> yes
            print(urgent, urgent > 0.5)
            val anger = [m, system: "Ты оцениваешь тон"] => "Насколько клиент зол? {ticket}" -> score(0..=3)
            print(anger.value, round(anger.mean, 2), anger.probs[3])
            val word = [m] => "Уровень?" -> score(["низкий", "высокий"])
            print(word, word.mean)
            '''))
        self.assertEqual(out, "tech (90%) tech 0.9 true 0.06\n0.8 true\n2 1.8 0.1\nвысокий (75%) 0.75\n")
        bodies = [r["body"] for r in mock.chat_requests()]
        first = bodies[0]
        self.assertEqual((first["max_tokens"], first["temperature"], first["logprobs"], first["top_logprobs"]),
                         (1, 0, True, 20))
        self.assertEqual(first["chat_template_kwargs"], {"enable_thinking": False})
        user = first["messages"][-1]["content"]
        self.assertIn("A. billing\nB. tech\nC. sales", user)
        self.assertTrue(user.startswith("Кто займётся обращением?"))
        self.assertIn("A. Yes\nB. No", bodies[1]["messages"][-1]["content"])
        self.assertTrue(bodies[2]["messages"][0]["content"].startswith("Ты оцениваешь тон"))
        self.assertIn("from the lowest to the highest", bodies[2]["messages"][-1]["content"])

    def test_options_with_descriptions(self):
        mock = self.serve()
        out = run_upl('import llm\nllm m\n'
                      'val d = m.choice("Куда?", {"billing": "деньги и счета", "tech": "ошибки и доступ"})\n'
                      'print(d.value, d.p)')
        self.assertEqual(out, "billing 0.7\n")
        self.assertIn("A. billing: деньги и счета\nB. tech: ошибки и доступ",
                      mock.chat_requests()[0]["body"]["messages"][-1]["content"])

    def test_decide_asks_every_question_about_one_text(self):
        def pick(body):
            text = body["messages"][-1]["content"]
            if "Question: Urgent?" in text:
                return {"A": 0.95, "B": 0.05}
            if "Question: Team?" in text:
                return {"C": 0.7, "A": 0.3}
            return {"A": 0.5, "B": 0.5}
        mock = self.serve(decide=pick)
        m = llm.Model()
        r = m.decide("Сервер упал, клиенты злятся", {"urgent": llm.Yes("Urgent?"),
                                                    "team": llm.Choice("Team?", ["billing", "sales", "tech"]),
                                                    "tone": llm.Score("Tone?", ["calm", "angry"])})
        self.assertEqual(list(r), ["urgent", "team", "tone"])
        self.assertEqual(r.urgent, 0.95)
        self.assertEqual((r.team.value, r.team.p), ("tech", 0.7))
        self.assertEqual(r.tone.mean, 0.5)
        texts = [q["body"]["messages"][-1]["content"] for q in mock.chat_requests()]
        self.assertTrue(all(t.startswith("Сервер упал, клиенты злятся\n\nQuestion: ") for t in texts))
        with self.assertRaises(UpsilError):
            m.decide("x", {"a": "not a question"})

    def test_a_server_that_refuses_template_kwargs(self):
        mock = self.serve(template_kwargs=False)
        m = llm.Model()
        self.assertEqual(m.yes("?"), 0.7)
        self.assertEqual(m.yes("?"), 0.7)
        sent = [("chat_template_kwargs" in r["body"]) for r in mock.chat_requests()]
        self.assertEqual(sent, [True, False, False])        # refused once, then never sent again

    def test_no_logprobs_is_a_clear_error(self):
        self.serve(logprobs=False)
        with self.assertRaises(llm.Error) as ctx:
            llm.Model().yes("?")
        self.assertIn("does not return probabilities (logprobs)", str(ctx.exception))

    def test_a_thinking_model_is_not_turned_into_confident_numbers(self):
        self.serve(decide=letters(**{"<think>": 0.97, "A": 0.02, "B": 0.01}))
        with self.assertRaises(llm.FormatError) as ctx:
            run_upl('import llm\nllm m\nprint([m] => "?" -> choice(["a", "b"]))')
        self.assertIn("'<think>'", str(ctx.exception))
        self.assertEqual(ctx.exception.reply, "<think>")

    def test_catching_decision_errors(self):
        self.serve(logprobs=False)
        out = run_upl('import llm\nllm m\n'
                      'try { print([m] => "?" -> yes) } catch (e: llm.Error) { print("нет вероятностей") }')
        self.assertEqual(out, "нет вероятностей\n")

    def test_runtime_checks_of_options(self):
        self.serve()
        m = llm.Model()
        for bad in (["only"], ["a", "a"], "abc", [["nested"], "x"]):
            with self.assertRaises(UpsilError):
                m.choice("?", bad)
        with self.assertRaises(UpsilError):
            m.score("?", range(0, 20))


class DecisionValueTest(UpsilTestCase):
    def test_equality_display_and_hash(self):
        d = llm.Decision("choice", ["a", "b"], [0.25, 0.75])
        self.assertEqual((d.value, d.p, d.mean), ("b", 0.75, None))
        self.assertTrue(d == "b" and d != "a")
        self.assertEqual(str(d), "b (75%)")
        self.assertEqual({d: 1}[d], 1)
        s = llm.Decision("score", [1, 2, 3], [0.2, 0.3, 0.5])
        self.assertAlmostEqual(s.mean, 2.3)
        self.assertEqual(run_upl("print(1)"), "1\n")


class CompileTest(UpsilTestCase):
    def test_compile_errors(self):
        self.assertCompileError('import llm\nllm m\nval x = [m] => "?" -> choice(["a"])', "from 2 to 26 options, here 1", 3)
        self.assertCompileError('import llm\nllm m\nval x = [m] => "?" -> choice(["a", "b", "a"])', "listed twice")
        self.assertCompileError('import llm\nllm m\nval x = [m] => "?" -> score(1..=11)', "from 2 to 10 levels, here 11")
        self.assertCompileError('import llm\nllm m\nval x = [m] => "?" -> yes()', "'-> yes' takes no options")
        self.assertCompileError('import llm\nllm m\nval x = [m] => "?" -> choice', "'-> choice' needs the options")
        self.assertCompileError('import llm\nllm m\nval x = [m] => "?" -> xml', "after a prompt: '-> json'")

    def test_words_stay_ordinary_names(self):
        self.assertRuns('val choice = 1\nval score = 2\nval yes = 3\nprint(choice + score + yes)', "6\n")


class SystemOneTest(DecisionCase):
    def test_protocol_and_results(self):
        seen = []

        def answer(body):
            seen.append(body)
            out = {}
            for key, q in body["questions"].items():
                if q["type"] == "noul":
                    out[key] = {"type": "noul", "noul": 0.91}
                elif q["type"] == "choice":
                    names = list(q["criteria"])
                    out[key] = {"type": "choice", "choice": names[-1], "confidence": 0.8,
                                "probabilities": {names[0]: 0.2, names[-1]: 0.8}}
                else:
                    out[key] = {"type": "score", "score": 1.4, "confidence": 0.6,
                                "probabilities": {"0": 0.1, "1": 0.4, "2": 0.5}, "legend": {}}
            return out
        mock = self.serve(systemone=answer)
        with env(TYPESAFE_API_KEY="ts-key"):
            j = llm.SystemOne(mock.url)            # an .../v1 address is accepted too
        out = run_upl(textwrap.dedent(f'''\
            import llm
            llm j = llm.SystemOne("{mock.url[:-3]}", api_key = "ts-key")
            val r = j.decide("Сервер упал", {{"urgent": llm.Yes("Срочно?"),
                                             "team": llm.Choice("Кому?", {{"billing": "деньги", "tech": "ошибки"}}),
                                             "tone": llm.Score("Тон?", ["спокойно", "недовольно", "зло"])}})
            print(r.urgent, r.team, r.tone.value, round(r.tone.mean, 2))
            print([j] => "Кому? Сервер упал" -> choice(["billing", "tech"]))
            try {{ print([j] => "Напиши письмо") }} catch (e) {{ print("текст не пишет") }}
            '''))
        self.assertEqual(out, "0.91 tech (80%) зло 1.4\ntech (80%)\nтекст не пишет\n")
        first = seen[0]
        self.assertEqual((first["model"], first["state"]), ("jev-latest", "Сервер упал"))
        self.assertEqual(first["questions"]["urgent"], {"type": "noul", "instructions": "Срочно?"})
        self.assertEqual(first["questions"]["team"]["criteria"], {"billing": "деньги", "tech": "ошибки"})
        self.assertEqual(first["questions"]["tone"]["criteria"], ["спокойно", "недовольно", "зло"])
        self.assertEqual(seen[1]["state"], "Кому? Сервер упал")
        posts = [r for r in mock.requests if r["path"] == "/v1/systemone"]
        self.assertEqual(posts[0]["headers"]["Authorization"], "Bearer ts-key")
        self.assertEqual(j.url, mock.url[:-3])

    def test_errors(self):
        mock = self.serve(require_key="right")
        with self.assertRaises(llm.Error) as ctx:
            llm.SystemOne(mock.url, api_key="wrong").yes("?")
        self.assertEqual(ctx.exception.status, 401)
        self.assertIn("TYPESAFE_API_KEY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
