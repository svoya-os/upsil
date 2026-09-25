# SPDX-License-Identifier: Apache-2.0
import contextlib
import os
import tempfile
import unittest

from mock_openai import MockOpenAI, free_port
from support import UpsilTestCase, env, lang, run_upl

from upsil.runtime import config, llm
from upsil.runtime._net import NetError


class LLMTestCase(UpsilTestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.mock = stack.enter_context(MockOpenAI())
        stack.enter_context(env(UPSIL_LLM_URL=self.mock.url, UPSIL_CONFIG=os.devnull, UPSIL_LLM_MODEL=None,
                                UPSIL_LLM_KEY=None, OPENAI_API_KEY=None, UPSIL_LANG="en"))
        self.stack = stack


class ModelTest(LLMTestCase):
    def test_ask_uses_the_first_listed_model(self):
        m = llm.Model()
        self.assertEqual(m.ask("hi"), "echo: hi")
        self.assertEqual(m.name, "mock-small")
        req = self.mock.chat_requests()[0]
        self.assertEqual(req["body"]["model"], "mock-small")
        self.assertEqual(req["body"]["messages"], [{"role": "user", "content": "hi"}])
        self.assertFalse(req["body"]["stream"])
        self.assertNotIn("Authorization", req["headers"])

    def test_model_name_sources(self):
        self.assertEqual(llm.Model("explicit").name, "explicit")
        with env(UPSIL_LLM_MODEL="from-env"):
            self.assertEqual(llm.Model().name, "from-env")
        self.assertEqual(llm.models(), ["mock-small", "mock-embed"])

    def test_no_request_until_first_use(self):
        llm.Model()
        self.assertEqual(self.mock.requests, [])

    def test_system_prompt_temperature_and_key(self):
        with env(UPSIL_LLM_KEY="secret"):
            m = llm.Model("x", system="default system", temperature=0.2)
        m.ask("q", system="be terse", max_tokens=5)
        body = self.mock.chat_requests()[0]["body"]
        self.assertEqual(body["messages"][0], {"role": "system", "content": "be terse"})
        self.assertEqual((body["temperature"], body["max_tokens"]), (0.2, 5))
        self.assertEqual(self.mock.chat_requests()[0]["headers"]["Authorization"], "Bearer secret")
        m.ask("q2")
        self.assertEqual(self.mock.chat_requests()[1]["body"]["messages"][0]["content"], "default system")

    def test_openai_api_key_is_used_too(self):
        with env(OPENAI_API_KEY="sk-test"):
            llm.Model("x").ask("q")
        self.assertEqual(self.mock.chat_requests()[0]["headers"]["Authorization"], "Bearer sk-test")

    def test_chat_with_history(self):
        m = llm.Model("x")
        history = [{"role": "user", "content": "one"}, {"role": "assistant", "content": "echo: one"},
                   {"role": "user", "content": "two"}]
        self.assertEqual(m.chat(history), "echo: two")
        self.assertEqual(len(self.mock.chat_requests()[0]["body"]["messages"]), 3)
        with self.assertRaises(llm.LLMError):
            m.chat(["not a message"])

    def test_json_mode(self):
        m = llm.Model("x")
        self.assertEqual(m.ask("data", json=True), {"echo": "data"})
        body = self.mock.chat_requests()[0]["body"]
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertIn("JSON", body["messages"][0]["content"])

    def test_json_mode_without_server_support(self):
        self.mock.json_mode = False
        m = llm.Model("x")
        self.assertEqual(m.ask("data", json=True), {"echo": "data"})
        self.assertEqual(m.ask("again", json=True), {"echo": "again"})
        with_format = [r for r in self.mock.chat_requests() if "response_format" in r["body"]]
        self.assertEqual(len(with_format), 1)    # refused once, then asked in words only

    def test_think_blocks_are_removed(self):
        self.mock.think = True
        m = llm.Model("x")
        self.assertEqual(m.ask("hi"), "echo: hi")
        self.assertEqual("".join(m.stream("hi")), "echo: hi")

    def test_stream(self):
        pieces = list(llm.Model("x").stream("a longer question"))
        self.assertGreater(len(pieces), 2)
        self.assertEqual("".join(pieces), "echo: a longer question")
        self.assertTrue(self.mock.chat_requests()[0]["body"]["stream"])

    def test_retries_while_the_model_loads(self):
        self.mock.fail_503 = 2
        saved = llm._RETRY_DELAY
        llm._RETRY_DELAY = 0.01
        try:
            self.assertEqual(llm.Model("x").ask("hi"), "echo: hi")
        finally:
            llm._RETRY_DELAY = saved
        self.assertEqual(len(self.mock.chat_requests()), 3)

    def test_bad_key(self):
        self.mock.require_key = "right"
        with env(UPSIL_LLM_KEY="wrong"), self.assertRaises(llm.LLMError) as cm:
            llm.Model("x").ask("hi")
        self.assertIn("refused the API key (HTTP 401). Set UPSIL_LLM_KEY or OPENAI_API_KEY", str(cm.exception))

    def test_other_http_errors_carry_the_server_message(self):
        m = llm.Model("x", url=self.mock.url + "/nope")
        with self.assertRaises(llm.LLMError) as cm:
            m.ask("hi")
        self.assertIn("Not found (HTTP 404)", str(cm.exception))
        self.assertEqual(cm.exception.status, 404)

    def test_timeout(self):
        self.mock.delay = 1.5
        with self.assertRaises(llm.LLMError) as cm:
            llm.Model("x", timeout=0.3).ask("hi")
        self.assertIn("did not answer within 0.3 s", str(cm.exception))

    def test_repr(self):
        self.assertEqual(repr(llm.Model("q", url="http://h:1/v1")), 'llm.Model("q", url="http://h:1/v1")')


class ServerDownTest(UpsilTestCase):
    def test_local_server_down_message(self):
        port = free_port()
        with env(UPSIL_LLM_URL=f"http://127.0.0.1:{port}/v1", UPSIL_CONFIG=os.devnull, UPSIL_LLM_MODEL="x"):
            for code, text in (("ru", f"Локальная модель не отвечает (127.0.0.1:{port}). В СОС: sos models serve"),
                               ("en", f"The local model is not responding (127.0.0.1:{port}). On SOS: sos models serve")):
                with lang(code):
                    with self.assertRaises(llm.LLMError) as cm:
                        llm.Model().ask("hi")
                    self.assertEqual(str(cm.exception), text)

    def test_default_address_is_the_sos_server(self):
        with env(UPSIL_LLM_URL=None, UPSIL_CONFIG=os.devnull):
            m = llm.Model("x")
        self.assertEqual(m.url, "http://127.0.0.1:8080/v1")
        with lang("ru"):
            self.assertEqual(str(m._net_error(NetError("connect", "refused", m.url))),
                             "Локальная модель не отвечает (127.0.0.1:8080). В СОС: sos models serve")

    def test_remote_server_down_message(self):
        m = llm.Model("x", url="https://api.example.com/v1")
        with lang("en"):
            self.assertEqual(str(m._net_error(NetError("connect", "Name or service not known", m.url))),
                             "The model server is not responding (api.example.com): Name or service not known")

    def test_prompt_operator_reports_the_server_down(self):
        port = free_port()
        with env(UPSIL_LLM_URL=f"http://127.0.0.1:{port}/v1", UPSIL_CONFIG=os.devnull, UPSIL_LLM_MODEL="x"), \
                lang("ru"):
            with self.assertRaises(llm.LLMError) as cm:
                run_upl('import llm\nllm m\nprint([m] => "hi")')
            self.assertIn("В СОС: sos models serve", str(cm.exception))


class ConfigTest(UpsilTestCase):
    TEXT = ('# settings\n[llm]\nurl = "http://gpu-box:8000/v1"  # comment\nmodel = \'qwen3.5-4b\'\ntimeout = 300\n'
            'temperature = 0.5\nflags = ["a", "b # not a comment"]\nstream = true\n\n[rag]\nbackend = "bm25"\n')

    def test_url_and_model_from_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.toml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.TEXT)
            with env(UPSIL_CONFIG=path, UPSIL_LLM_URL=None, UPSIL_LLM_MODEL=None):
                m = llm.Model()
                self.assertEqual((m.url, m.name, m.timeout), ("http://gpu-box:8000/v1", "qwen3.5-4b", 300.0))
                with env(UPSIL_LLM_URL="http://other:1/v1/"):
                    self.assertEqual(llm.Model().url, "http://other:1/v1")   # the environment wins

    def test_xdg_config_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "upsil"))
            with open(os.path.join(tmp, "upsil", "config.toml"), "w", encoding="utf-8") as f:
                f.write('[llm]\nurl = "http://xdg:9/v1"\n')
            with env(UPSIL_CONFIG=None, XDG_CONFIG_HOME=tmp, UPSIL_LLM_URL=None):
                self.assertEqual(llm.default_url(), "http://xdg:9/v1")

    def test_subset_parser_matches_tomllib(self):
        expected = {"llm": {"url": "http://gpu-box:8000/v1", "model": "qwen3.5-4b", "timeout": 300,
                            "temperature": 0.5, "flags": ["a", "b # not a comment"], "stream": True},
                    "rag": {"backend": "bm25"}}
        self.assertEqual(config.parse_toml_subset(self.TEXT), expected)
        self.assertEqual(config.parse_toml(self.TEXT), expected)
        self.assertEqual(config.parse_toml_subset('[a.b]\n"k" = "x\\ty"\nn = -1_000\n'),
                         {"a": {"b": {"k": "x\ty", "n": -1000}}})

    def test_subset_parser_errors(self):
        from upsil.errors import UpsilError
        with lang("en"):
            with self.assertRaises(UpsilError) as cm:
                config.parse_toml_subset("[llm]\nurl http://x\n", "c.toml")
            self.assertIn("c.toml:2: bad settings file", str(cm.exception))
            with self.assertRaises(UpsilError):
                config.parse_toml_subset('x = "open\n')

    def test_missing_config_is_empty(self):
        with env(UPSIL_CONFIG="/nonexistent/upsil.toml"):
            self.assertEqual(config.load(), {})


class JsonReplyTest(UpsilTestCase):
    def test_parse_json_reply(self):
        self.assertEqual(llm.parse_json_reply('{"a": 1}'), {"a": 1})
        self.assertEqual(llm.parse_json_reply('```json\n[1, 2]\n```'), [1, 2])
        self.assertEqual(llm.parse_json_reply('<think>x</think>Here you go: {"ok": true} bye'), {"ok": True})
        with lang("en"), self.assertRaises(llm.LLMError) as cm:
            llm.parse_json_reply("no json here")
        self.assertIn("not valid JSON", str(cm.exception))


class PromptOperatorTest(LLMTestCase):
    def test_prompt_operator_end_to_end(self):
        src = ('import llm\nllm m = llm.Model()\nval q = "RAG"\n'
               'print([m] => "Explain {q}")\n'
               'print([m, system: "You are terse"] => "Hi")\n'
               'val data = [m] => "Give JSON" -> json\nprint(data["echo"])\n'
               'llm dflt\nprint([dflt] => """\n    multi\n    line\n    """)\n')
        self.assertEqual(run_upl(src), "echo: Explain RAG\necho: Hi\nGive JSON\necho: multi\nline\n")
        systems = [r["body"]["messages"][0] for r in self.mock.chat_requests()]
        self.assertEqual(systems[1], {"role": "system", "content": "You are terse"})

    def test_stream_from_upsil(self):
        src = 'import llm\nval m = llm.Model()\nfor (piece in m.stream("abcdefghij")) { print(piece, end = "|") }'
        self.assertEqual(run_upl(src), "echo|: ab|cdef|ghij|")


if __name__ == "__main__":
    unittest.main()
