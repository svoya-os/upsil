# SPDX-License-Identifier: Apache-2.0
import contextlib
import io
import os
import tempfile
import unittest

from mock_openai import MockOpenAI, free_port
from support import UpsilTestCase, env, run_upl

from upsil.errors import UpsilError
from upsil.runtime import rag
from upsil.runtime.llm import LLMError

DOCS = [
    ("Paris is the capital of France.", {"topic": "geo"}),
    ("The Moon orbits the Earth once a month.", {"topic": "space"}),
    ("Python is a programming language.", {"topic": "code"}),
]


class RagTestCase(UpsilTestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.mock = stack.enter_context(MockOpenAI())
        stack.enter_context(env(UPSIL_LLM_URL=self.mock.url, UPSIL_CONFIG=os.devnull, UPSIL_LLM_MODEL=None,
                                UPSIL_LANG="en"))
        rag._notice_shown = False
        self.stderr = io.StringIO()
        stack.enter_context(contextlib.redirect_stderr(self.stderr))

    def filled(self, **kwargs):
        store = rag.VectorStore(**kwargs)
        for text, meta in DOCS:
            store.add(text, meta)
        return store


class EmbeddingsTest(RagTestCase):
    def test_semantic_search(self):
        store = self.filled()
        self.assertEqual(store.backend, "embeddings")
        hits = store.search("what orbits the Earth", k=2)
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0].text, "The Moon orbits the Earth once a month.")
        self.assertEqual((hits[0]["meta"], hits[0].id), ({"topic": "space"}, 1))
        self.assertGreater(hits[0].score, hits[1].score)
        self.assertEqual(self.stderr.getvalue(), "")
        embed_requests = [r for r in self.mock.requests if r["path"] == "/v1/embeddings"]
        self.assertEqual(embed_requests[0]["body"]["model"], "mock-small")

    def test_embedding_model_can_be_chosen(self):
        store = rag.VectorStore("mock-embed")
        store.add("x")
        body = [r for r in self.mock.requests if r["path"] == "/v1/embeddings"][0]["body"]
        self.assertEqual(body, {"model": "mock-embed", "input": ["x"]})

    def test_forced_embeddings_fail_loudly(self):
        self.mock.embeddings = False
        with self.assertRaises(LLMError) as cm:
            rag.VectorStore(backend="embeddings").add("x")
        self.assertIn("HTTP 501", str(cm.exception))


class FallbackTest(RagTestCase):
    def test_bm25_when_the_server_has_no_embeddings(self):
        self.mock.embeddings = False
        store = self.filled()
        self.assertEqual(store.backend, "bm25")
        self.assertEqual(store.search("capital of France")[0].text, "Paris is the capital of France.")
        store2 = self.filled()
        store2.search("moon")
        notice = self.stderr.getvalue()
        self.assertEqual(notice.count("upsil rag:"), 1)     # said once per process
        self.assertIn("no embeddings from the model server", notice)
        self.assertIn("searching by words (BM25)", notice)
        self.assertIn("does not support embeddings", notice)

    def test_bm25_when_the_server_is_down(self):
        with env(UPSIL_LLM_URL=f"http://127.0.0.1:{free_port()}/v1"):
            store = self.filled()
        self.assertEqual(store.backend, "bm25")
        self.assertIn("The local model is not responding", self.stderr.getvalue())

    def test_forced_bm25_makes_no_requests(self):
        store = self.filled(backend="bm25")
        self.assertEqual(store.search("programming language")[0].meta, {"topic": "code"})
        self.assertEqual(self.mock.requests, [])
        self.assertEqual(self.stderr.getvalue(), "")

    def test_notice_in_russian(self):
        self.mock.embeddings = False
        with env(UPSIL_LANG="ru"):
            self.filled()
        self.assertIn("поиск будет по словам (BM25)", self.stderr.getvalue())

    def test_search_falls_back_when_embeddings_disappear(self):
        store = self.filled()
        self.mock.embeddings = False
        self.assertEqual(store.search("Moon")[0].id, 1)
        self.assertEqual(store.backend, "bm25")


class StoreTest(RagTestCase):
    def test_empty_store_and_k(self):
        store = rag.VectorStore(backend="bm25")
        self.assertEqual(store.search("anything"), [])
        store = self.filled(backend="bm25")
        self.assertEqual(len(store.search("the", k=1)), 1)
        self.assertEqual(store.search("zzz"), [])
        self.assertEqual(len(store), 3)

    def test_russian_endings(self):
        store = rag.VectorStore(backend="bm25")
        store.add("Москва — столица России.")
        store.add("Луна вращается вокруг Земли.")
        self.assertEqual(store.search("столицы москвы")[0].id, 0)
        self.assertEqual(store.search("вокруг земле луну")[0].id, 1)
        self.assertEqual(rag.stem("столицы"), rag.stem("столица"))
        self.assertEqual(rag.stem("orbits"), rag.stem("orbiting"))

    def test_context(self):
        store = self.filled(backend="bm25")
        self.assertEqual(store.context("Paris France", k=1), "Paris is the capital of France.")

    def test_add_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "sub"))
            os.makedirs(os.path.join(tmp, ".obsidian"))
            with open(os.path.join(tmp, "a.md"), "w", encoding="utf-8") as f:
                f.write("# Backups\n\nUse restic every night.\n")
            with open(os.path.join(tmp, "sub", "b.md"), "w", encoding="utf-8") as f:
                f.write("\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(8)))
            with open(os.path.join(tmp, "c.txt"), "w", encoding="utf-8") as f:
                f.write("not markdown")
            with open(os.path.join(tmp, ".obsidian", "d.md"), "w", encoding="utf-8") as f:
                f.write("hidden settings")
            store = rag.VectorStore(backend="bm25", chunk_size=800)
            n = store.add_dir(tmp)
            self.assertEqual(n, len(store))
            sources = {d["meta"]["source"] for d in store.docs}
            self.assertEqual(sources, {"a.md", "sub/b.md"})
            self.assertGreater(n, 2)
            self.assertTrue(all(len(d["text"]) <= 800 for d in store.docs))
            self.assertEqual(store.search("restic backups")[0].meta, {"source": "a.md", "chunk": 0})
            self.assertEqual(store.add_dir(tmp, glob="*.txt"), 1)
            with self.assertRaises(UpsilError):
                store.add_dir(os.path.join(tmp, "missing"))

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            for backend in ("embeddings", "bm25"):
                path = os.path.join(tmp, f"{backend}.json")
                store = self.filled(backend=backend)
                store.save(path)
                loaded = rag.VectorStore.load(path)
                self.assertEqual((loaded.backend, len(loaded)), (backend, 3))
                self.assertEqual(loaded.search("Moon Earth")[0].id, 1)
            bad = os.path.join(tmp, "bad.json")
            with open(bad, "w") as f:
                f.write('{"hello": 1}')
            with self.assertRaises(UpsilError) as cm:
                rag.VectorStore.load(bad)
            self.assertIn("not a saved rag.VectorStore", str(cm.exception))

    def test_unknown_backend(self):
        with self.assertRaises(UpsilError):
            rag.VectorStore(backend="faiss")

    def test_split_text(self):
        chunks = rag.split_text("a\n\nb\n\n" + "x " * 700, 500)
        self.assertEqual(chunks[0], "a\n\nb")
        self.assertTrue(all(len(c) <= 500 for c in chunks))
        self.assertEqual("".join(chunks[1:]).replace(" ", ""), "x" * 700)


class UpsilProgramTest(RagTestCase):
    def test_vector_store_from_upsil(self):
        src = ('import rag\nvector_store db = rag.VectorStore(backend = "bm25")\n'
               'db.add("Paris is the capital of France.", {"id": "p"})\n'
               'db.add("The Moon orbits the Earth.")\n'
               'val hits = db.search("What orbits the Earth?", k = 1)\n'
               'for (h in hits) { print(h.text, h.meta, h.score > 0) }\n'
               'vector_store auto\nauto.add("x y z")\nprint(len(auto), auto.search("y")[0].text)\n')
        self.assertEqual(run_upl(src), "The Moon orbits the Earth. {} true\n1 x y z\n")

    def test_vector_store_declaration_checks_the_value(self):
        with self.assertRaises(UpsilError):
            run_upl("vector_store db = [1, 2]")


if __name__ == "__main__":
    unittest.main()
