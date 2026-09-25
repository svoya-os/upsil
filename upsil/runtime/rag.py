# SPDX-License-Identifier: Apache-2.0
"""rag: a small document store for retrieval-augmented generation.

    import rag
    vector_store db = rag.VectorStore()
    db.add_dir("notes", glob = "*.md")
    for (hit in db.search("how do I back up?", k = 3)) {
        print("{hit.score}  {hit.meta["source"]}")
    }
    db.save("notes.index.json")

Search is semantic when the model server offers ``POST /embeddings``
(cosine similarity, computed in pure Python). When it does not, the store
says so once on stderr and searches by words instead (BM25 with a light
Russian/English ending normalisation). Choose explicitly with
``rag.VectorStore(backend = "embeddings")`` or ``backend = "bm25"``, or with
``[rag] backend`` in the config file. Everything is kept in memory and saved
as JSON; it is meant for notes and documents, not for millions of chunks.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..errors import UpsilError
from ..i18n import tr
from . import config as _config
from .llm import LLMError, Model
from .prelude import Record

__all__ = ["VectorStore", "Result"]

FORMAT = "upsil-rag"
FORMAT_VERSION = 1
BACKENDS = ("auto", "embeddings", "bm25")
_EMBED_BATCH = 32
_notice_shown = False


class Result(Record):
    """A search hit: ``hit.text``, ``hit.score``, ``hit.meta``, ``hit.id`` (or ``hit["text"]``...)."""

    __slots__ = ()


class VectorStore:
    def __init__(self, model: Optional[str] = None, *, backend: Optional[str] = None,
                 url: Optional[str] = None, chunk_size: int = 1000):
        backend = backend or _config.get("rag", "backend") or "auto"
        if backend not in BACKENDS:
            raise UpsilError(f"rag.VectorStore: unknown backend {backend!r} (auto, embeddings, bm25)",
                             f"rag.VectorStore: неизвестный backend {backend!r} (auto, embeddings, bm25)")
        self.requested = backend
        # decided by the first add() in "auto" mode
        self.backend: Optional[str] = None if backend == "auto" else backend
        self.embed_model: Optional[str] = model or _config.get("rag", "embed_model") or None
        self.chunk_size = int(chunk_size)
        self.docs: List[Dict[str, Any]] = []
        self._url = url
        self._client: Optional[Model] = None
        self._bm25: Optional[_BM25] = None

    def __len__(self) -> int:
        return len(self.docs)

    def __repr__(self) -> str:
        return f"rag.VectorStore({len(self.docs)} documents, backend={self.backend or 'auto'})"

    __str__ = __repr__

    # ------------------------------------------------------------------ adding
    def add(self, text: Any, meta: Optional[Dict[str, Any]] = None) -> int:
        """Add one document (as is, without splitting); returns its id."""
        return self._add_many([(text, meta)])[0]

    def add_dir(self, path: str, glob: str = "*.md") -> int:
        """Add the files under ``path`` that match ``glob`` (recursively, skipping hidden
        folders), split into chunks of about ``chunk_size`` characters; returns the
        number of chunks. Each chunk gets ``meta = {"source": relative path, "chunk": n}``."""
        root = Path(str(path)).expanduser()
        if not root.is_dir():
            raise UpsilError(f"add_dir: not a folder: {path}", f"add_dir: это не папка: {path}")
        items: List[Tuple[str, Dict[str, Any]]] = []
        for file in sorted(root.rglob(glob)):
            rel = file.relative_to(root)
            if not file.is_file() or any(part.startswith(".") for part in rel.parts):
                continue
            text = file.read_text(encoding="utf-8", errors="replace")
            for n, piece in enumerate(split_text(text, self.chunk_size)):
                items.append((piece, {"source": rel.as_posix(), "chunk": n}))
        if items:
            self._add_many(items)
        return len(items)

    def _add_many(self, items: Sequence[Tuple[Any, Optional[Dict[str, Any]]]]) -> List[int]:
        texts = [t if isinstance(t, str) else _show(t) for t, _ in items]
        vectors = self._embed_docs(texts) if self.backend != "bm25" else None
        ids = []
        for i, (_, meta) in enumerate(items):
            doc: Dict[str, Any] = {"id": len(self.docs), "text": texts[i], "meta": dict(meta or {})}
            if vectors is not None:
                doc["vector"] = vectors[i]
            self.docs.append(doc)
            ids.append(doc["id"])
        self._bm25 = None
        return ids

    # ------------------------------------------------------------------ searching
    def search(self, query: Any, k: int = 3) -> List[Result]:
        """The ``k`` best matches, best first."""
        k = int(k)
        query = query if isinstance(query, str) else _show(query)
        if not self.docs or k <= 0:
            return []
        if self.backend == "embeddings":
            try:
                qv = self._embed([query])[0]
            except LLMError as exc:
                if self.requested != "auto":
                    raise
                self._fall_back(exc)
            else:
                scored = [(_cosine(qv, d["vector"]), d) for d in self.docs]
                scored.sort(key=lambda sd: (-sd[0], sd[1]["id"]))
                return [_result(d, s) for s, d in scored[:k]]
        index = self._bm25 or _BM25([tokenize(d["text"]) for d in self.docs])
        self._bm25 = index
        scores = index.scores(tokenize(query))
        ranked = sorted((i for i, s in enumerate(scores) if s > 0), key=lambda i: (-scores[i], i))
        return [_result(self.docs[i], scores[i]) for i in ranked[:k]]

    def context(self, query: Any, k: int = 3, sep: str = "\n\n---\n\n") -> str:
        """The texts of the best matches joined together, ready for a prompt."""
        return sep.join(hit["text"] for hit in self.search(query, k))

    # ------------------------------------------------------------------ files
    def save(self, path: str) -> None:
        data = {"format": FORMAT, "version": FORMAT_VERSION, "backend": self.backend,
                "embed_model": self.embed_model, "docs": self.docs}
        target = Path(str(path)).expanduser()
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)

    @classmethod
    def load(cls, path: str) -> "VectorStore":
        source = Path(str(path)).expanduser()
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except ValueError:
            data = None
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            raise UpsilError(f"{path}: not a saved rag.VectorStore", f"{path}: это не сохранённый rag.VectorStore")
        if data.get("version") != FORMAT_VERSION:
            raise UpsilError(f"{path}: unsupported index version {data.get('version')}",
                             f"{path}: неподдерживаемая версия индекса {data.get('version')}")
        store = cls(model=data.get("embed_model"))
        store.backend = data.get("backend")
        store.docs = list(data.get("docs") or [])
        return store

    # ------------------------------------------------------------------ embeddings
    def _embed(self, texts: List[str]) -> List[List[float]]:
        if self._client is None:
            self._client = Model(self.embed_model, url=self._url)
        out: List[List[float]] = []
        for i in range(0, len(texts), _EMBED_BATCH):
            out.extend(self._client.embed(texts[i:i + _EMBED_BATCH], model=self.embed_model))
        return out

    def _embed_docs(self, texts: List[str]) -> Optional[List[List[float]]]:
        try:
            vectors = self._embed(texts)
        except LLMError as exc:
            if self.requested != "auto":
                raise
            self._fall_back(exc)
            return None
        dims = {len(v) for v in vectors} | {len(d["vector"]) for d in self.docs if "vector" in d}
        if len(dims) > 1:
            raise UpsilError("rag: embeddings of different sizes; was the embedding model changed?",
                             "rag: эмбеддинги разной длины; сменилась модель эмбеддингов?")
        self.backend = "embeddings"
        return vectors

    def _fall_back(self, exc: Exception) -> None:
        global _notice_shown
        self.backend = "bm25"
        for d in self.docs:
            d.pop("vector", None)
        self._bm25 = None
        if not _notice_shown:
            _notice_shown = True
            reason = str(exc)
            if len(reason) > 160:
                reason = reason[:160] + "..."
            sys.stderr.write(tr(
                f"upsil rag: no embeddings from the model server ({reason}); searching by words (BM25) instead.\n",
                f"upsil rag: сервер моделей не отдаёт эмбеддинги ({reason}); поиск будет по словам (BM25).\n"))
            sys.stderr.flush()


def _result(doc: Dict[str, Any], score: float) -> Result:
    return Result(id=doc["id"], text=doc["text"], score=round(float(score), 4), meta=doc["meta"])


def _show(value: Any) -> str:
    from .prelude import show
    return show(value)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


# ---------------------------------------------------------------------- text

def split_text(text: str, size: int = 1000) -> List[str]:
    """Split text into chunks of at most ``size`` characters, by paragraphs when possible."""
    size = max(100, int(size))
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    current = ""
    for para in paragraphs:
        while len(para) > size:                       # a very long paragraph: cut at a space
            cut = para.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:cut].strip())
            para = para[cut:].strip()
        if current and len(current) + 2 + len(para) > size:
            chunks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


_RU_ENDINGS = sorted((
    "иями", "ями", "ами", "ого", "его", "ому", "ему", "ыми", "ими", "иях", "ях", "ах", "ов", "ев",
    "ей", "ой", "ий", "ый", "ая", "яя", "ое", "ее", "ые", "ие", "ую", "юю", "ом", "ем", "ам", "ям",
    "ешь", "ишь", "ете", "ите", "ет", "ит", "ут", "ют", "ат", "ят", "ть", "ия", "ию",
    "а", "я", "о", "е", "ы", "и", "у", "ю", "ь", "й",
), key=len, reverse=True)
_EN_ENDINGS = ("ing", "ed", "s")


def stem(word: str) -> str:
    """A light, predictable normalisation of Russian and English word endings."""
    if not word or word.isdigit():
        return word
    if "Ѐ" <= word[0] <= "ӿ":
        for ending in _RU_ENDINGS:
            if word.endswith(ending) and len(word) - len(ending) >= 3:
                return word[:-len(ending)]
        return word
    for ending in _EN_ENDINGS:
        if ending == "s" and word.endswith("ss"):
            continue
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[:-len(ending)]
    return word


def tokenize(text: str) -> List[str]:
    words = re.findall(r"\w+", text.lower().replace("ё", "е"))
    return [stem(w) for w in words if len(w) > 1 or w.isdigit()]


class _BM25:
    def __init__(self, docs: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(d) for d in docs]
        self.lengths = [len(d) for d in docs]
        self.avgdl = (sum(self.lengths) / len(docs)) if docs else 0.0
        df: Counter = Counter()
        for d in docs:
            df.update(set(d))
        n = len(docs)
        self.idf = {t: math.log((n - c + 0.5) / (c + 0.5) + 1.0) for t, c in df.items()}

    def scores(self, query: Iterable[str]) -> List[float]:
        terms = [t for t in dict.fromkeys(query) if t in self.idf]
        out = []
        for tf, dl in zip(self.tf, self.lengths):
            s = 0.0
            norm = self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1.0))
            for t in terms:
                f = tf.get(t, 0)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + norm)
            out.append(s)
        return out
