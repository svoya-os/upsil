# SPDX-License-Identifier: Apache-2.0
"""llm: talk to a language model over an OpenAI-compatible HTTP API.

    import llm
    llm m = llm.Model("qwen3.5-4b")
    print([m] => "Say hi")                  // the prompt operator calls m.ask
    for (piece in m.stream("Tell a story")) { print(piece, end = "") }
    val team = [m] => "Who handles: {t}" -> choice(["billing", "tech"])   // a decision: m.choice

Where the server is (first match wins):

1. ``llm.Model(url = ...)``
2. the ``UPSIL_LLM_URL`` environment variable
3. ``[llm] url`` in ``~/.config/upsil/config.toml``
4. ``http://127.0.0.1:8080/v1`` -- the local server of SOS (``sos models serve``)

The model name comes from ``llm.Model("name")``, ``UPSIL_LLM_MODEL``,
``[llm] model`` or, failing that, the first model the server lists at
``/models``. An API key is optional (``UPSIL_LLM_KEY`` or ``OPENAI_API_KEY``),
so cloud endpoints work too. Reasoning blocks (``<think>...</think>``) that
some local models print are removed from replies.
"""

from __future__ import annotations

import json as _json
import os
import re
import socket
import time
import urllib.parse
from typing import Any, Dict, Iterator, List, Optional, Union

from ..errors import UpsilError
from . import _decide
from . import config as _config
from ._decide import Choice, Decision, Question, Score, Yes
from ._net import HttpError, NetError, is_loopback, open_url, read_all

__all__ = ["Model", "SystemOne", "LLMError", "Error", "FormatError", "models", "default_url",
           "Yes", "Choice", "Score", "Decision"]

DEFAULT_URL = "http://127.0.0.1:8080/v1"
DEFAULT_TIMEOUT = 120.0
JSON_INSTRUCTION = "Answer with one valid JSON value only: no explanations, no code fences."
_RETRY_DELAY = 1.0          # seconds, doubled per retry while the server loads a model (HTTP 503)


class LLMError(UpsilError):
    """A model call failed; ``status`` is the HTTP status when there was one."""

    def __init__(self, en: str, ru: Optional[str] = None, *, status: Optional[int] = None):
        super().__init__(en, ru)
        self.status = status


class FormatError(LLMError):
    """The reply is not the JSON that was asked for (``-> json`` / ``-> json(schema)``); ``reply`` is its text."""

    def __init__(self, en: str, ru: Optional[str] = None, *, reply: str = ""):
        super().__init__(en, ru)
        self.reply = reply


# `catch (e: llm.Error)` / `catch (e: llm.FormatError)`
Error = LLMError


# ---------------------------------------------------------------------- JSON shapes
# A schema is an UpsiL value: str int float bool list dict (types), [T] (a list of T),
# ["a", "b"] (one of these values), {"key": T, "note?": T} (an object; "?" = optional), null.

def _is_type(x: Any, t: type) -> bool:
    if x is t:
        return True
    if t is str:
        from .prelude import str as upsil_str
        return x is upsil_str
    return False


def _is_enum(schema: Any) -> bool:
    return (isinstance(schema, list) and len(schema) >= 1
            and all(v is None or isinstance(v, (str, int, float, bool)) for v in schema)
            and not (len(schema) == 1 and isinstance(schema[0], (list, dict))))


def _check_schema(schema: Any, where: str = "schema") -> None:
    if schema is None or any(_is_type(schema, t) for t in (str, int, float, bool, list, dict)):
        return
    if isinstance(schema, dict):
        for k, v in schema.items():
            if not isinstance(k, str):
                raise UpsilError(f"{where}: keys of a JSON shape are strings", f"{where}: ключи в описании JSON — строки")
            _check_schema(v, f"{where}.{k}")
        return
    if isinstance(schema, list):
        if len(schema) == 1 and not _is_enum(schema):
            _check_schema(schema[0], f"{where}[]")
            return
        if _is_enum(schema):
            return
    from .prelude import show
    raise UpsilError(f"{where}: {show(schema)} is not a JSON shape (use str, int, float, bool, list, dict, [T], "
                     f"[\"a\", \"b\"] or {{\"key\": T}})",
                     f"{where}: {show(schema)} — не описание JSON (используйте str, int, float, bool, list, dict, "
                     f"[T], [\"a\", \"b\"] или {{\"ключ\": T}})")


def _field(key: str) -> tuple:
    return (key[:-1], True) if key.endswith("?") else (key, False)


def describe_shape(schema: Any) -> str:
    """The shape as a JSON-like skeleton, for the model: {"label": "pos" | "neg", "score": number}."""
    if schema is None:
        return "null"
    for t, word in ((bool, "true | false"), (int, "integer"), (float, "number"), (str, "string"),
                    (list, "[...]"), (dict, "{...}")):
        if _is_type(schema, t):
            return word
    if isinstance(schema, dict):
        parts = []
        for k, v in schema.items():
            name, optional = _field(k)
            parts.append(f"{_json.dumps(name, ensure_ascii=False)}{'?' if optional else ''}: {describe_shape(v)}")
        return "{" + ", ".join(parts) + "}"
    if isinstance(schema, list):
        if _is_enum(schema):
            return " | ".join(_json.dumps(v, ensure_ascii=False) for v in schema)
        return "[" + describe_shape(schema[0]) + ", ...]"
    return "?"


def json_schema(schema: Any) -> Dict[str, Any]:
    """The shape as JSON Schema (for servers that constrain the output: llama.cpp, OpenAI)."""
    if schema is None:
        return {"type": "null"}
    for t, js in ((bool, {"type": "boolean"}), (int, {"type": "integer"}), (float, {"type": "number"}),
                  (str, {"type": "string"}), (list, {"type": "array"}), (dict, {"type": "object"})):
        if _is_type(schema, t):
            return dict(js)
    if isinstance(schema, dict):
        props, required = {}, []
        for k, v in schema.items():
            name, optional = _field(k)
            props[name] = json_schema(v)
            if not optional:
                required.append(name)
        return {"type": "object", "properties": props, "required": required}
    if isinstance(schema, list):
        if _is_enum(schema):
            return {"enum": list(schema)}
        return {"type": "array", "items": json_schema(schema[0])}
    return {}


def _kind(value: Any) -> tuple:
    from .prelude import show
    if value is None:
        return "null", "null"
    if isinstance(value, bool):
        return "a boolean", "логическое значение"
    if isinstance(value, (int, float)):
        return f"the number {show(value)}", f"число {show(value)}"
    if isinstance(value, str):
        short = value if len(value) <= 40 else value[:40] + "..."
        return f"the string {_json.dumps(short, ensure_ascii=False)}", f"строка {_json.dumps(short, ensure_ascii=False)}"
    if isinstance(value, list):
        return "a list", "список"
    if isinstance(value, dict):
        return "an object", "объект"
    return type(value).__name__, type(value).__name__


def conform(value: Any, schema: Any, path: str = "") -> Any:
    """Check a parsed reply against a shape; numbers are converted where it is lossless (3.0 -> 3)."""
    where_en = f"'{path}'" if path else "the answer"
    where_ru = f"«{path}»" if path else "ответ"

    def bad(expected_en: str, expected_ru: str) -> FormatError:
        got_en, got_ru = _kind(value)
        return FormatError(f"{where_en}: expected {expected_en}, got {got_en}",
                           f"{where_ru}: ожидалось {expected_ru}, получено: {got_ru}")

    if schema is None:
        if value is not None:
            raise bad("null", "null")
        return None
    if _is_type(schema, bool):
        if not isinstance(value, bool):
            raise bad("true or false", "true или false")
        return value
    if _is_type(schema, int):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not value.is_integer()):
            raise bad("an integer", "целое число")
        return int(value)
    if _is_type(schema, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise bad("a number", "число")
        return float(value)
    if _is_type(schema, str):
        if not isinstance(value, str):
            raise bad("a string", "строка")
        return value
    if _is_type(schema, list):
        if not isinstance(value, list):
            raise bad("a list", "список")
        return value
    if _is_type(schema, dict):
        if not isinstance(value, dict):
            raise bad("an object", "объект")
        return value
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            raise bad("an object " + describe_shape(schema), "объект " + describe_shape(schema))
        out = dict(value)
        for k, sub in schema.items():
            name, optional = _field(k)
            inner = f"{path}.{name}" if path else name
            if name not in value:
                if optional:
                    continue
                raise FormatError(f"'{inner}' is missing", f"нет поля «{inner}»")
            out[name] = conform(value[name], sub, inner)
        return out
    if isinstance(schema, list):
        if _is_enum(schema):
            if value not in schema or isinstance(value, bool) != any(isinstance(v, bool) for v in schema if v == value):
                options = ", ".join(_json.dumps(v, ensure_ascii=False) for v in schema)
                raise bad(f"one of {options}", f"одно из: {options}")
            return value
        if not isinstance(value, list):
            raise bad("a list", "список")
        return [conform(v, schema[0], f"{path}[{i}]") for i, v in enumerate(value)]
    return value


def default_url() -> str:
    return str(os.environ.get("UPSIL_LLM_URL") or _config.get("llm", "url") or DEFAULT_URL).rstrip("/")


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    from .prelude import show
    return show(value)


def _strip_think(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    if "<think>" in text:               # an unfinished block: the reply was cut off
        text = text.split("<think>", 1)[0]
    return text.strip()


class _ThinkFilter:
    """Removes <think>...</think> from a stream of text pieces."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self.inside = False
        self.buf = ""
        self.started = False

    def feed(self, piece: str) -> str:
        self.buf += piece
        out: List[str] = []
        while self.buf:
            token = self.CLOSE if self.inside else self.OPEN
            idx = self.buf.find(token)
            if idx < 0:
                keep = _partial_suffix(self.buf, token)
                if not self.inside:
                    out.append(self.buf[:len(self.buf) - keep])
                self.buf = self.buf[len(self.buf) - keep:] if keep else ""
                break
            if not self.inside:
                out.append(self.buf[:idx])
            self.buf = self.buf[idx + len(token):]
            self.inside = not self.inside
        text = "".join(out)
        if not self.started:            # no blank lines before the first visible word
            text = text.lstrip()
            self.started = bool(text)
        return text

    def flush(self) -> str:
        rest, self.buf = ("" if self.inside else self.buf), ""
        return rest


def _partial_suffix(text: str, token: str) -> int:
    for n in range(min(len(token) - 1, len(text)), 0, -1):
        if text.endswith(token[:n]):
            return n
    return 0


def parse_json_reply(text: str) -> Any:
    """Parse a model reply that should be JSON (tolerates ```json fences and chatter)."""
    t = _strip_think(text).strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    try:
        return _json.loads(t)
    except ValueError:
        pass
    decoder = _json.JSONDecoder()
    for i, ch in enumerate(t):
        if ch in "{[":
            try:
                return decoder.raw_decode(t, i)[0]
            except ValueError:
                continue
    short = t if len(t) <= 200 else t[:200] + "..."
    raise FormatError(f"The model's reply is not valid JSON: {short!r}",
                      f"Ответ модели — не JSON: {short!r}", reply=t)


class Model:
    """A chat model on an OpenAI-compatible server. Nothing is sent until the first call."""

    def __init__(self, name: Optional[str] = None, *, url: Optional[str] = None, api_key: Optional[str] = None,
                 timeout: Optional[float] = None, temperature: Optional[float] = None,
                 max_tokens: Optional[int] = None, system: Optional[str] = None, json_retries: int = 1):
        self.url = (url or default_url()).rstrip("/")
        self.json_retries = max(0, int(json_retries))
        self._name = name or os.environ.get("UPSIL_LLM_MODEL") or _config.get("llm", "model") or None
        if api_key is None:
            api_key = os.environ.get("UPSIL_LLM_KEY") or os.environ.get("OPENAI_API_KEY") or None
        self.api_key = api_key
        configured = timeout if timeout is not None else _config.get("llm", "timeout")
        self.timeout = float(configured) if configured else DEFAULT_TIMEOUT
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system = system
        self._json_mode = True          # send response_format until the server refuses it
        self._schema_mode = True        # … and with a JSON Schema, until the server refuses that
        self._thinking_off = True       # ask local servers for no <think> in decisions, until refused

    # ------------------------------------------------------------------ info
    @property
    def name(self) -> str:
        if not self._name:
            names = self.models()
            if not names:
                raise LLMError(f"The model server at {self._host()} has no models. On SOS: sos models suggest",
                               f"На сервере моделей {self._host()} нет ни одной модели. В СОС: sos models suggest")
            self._name = names[0]
        return self._name

    def __repr__(self) -> str:
        return f'llm.Model("{self._name or "?"}", url="{self.url}")'

    __str__ = __repr__

    def models(self) -> List[str]:
        """Names of the models the server offers."""
        try:
            data = self._request("GET", self.url + "/models")
        except LLMError as exc:
            if exc.status == 404 and self.url.endswith("/v1"):
                data = self._request("GET", self.url[:-3] + "/models")
            else:
                raise
        items: Any = data
        if isinstance(data, dict):
            items = data.get("data") or data.get("models") or []
        names: List[str] = []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict):
                n = item.get("id") or item.get("name") or item.get("model")
                if n:
                    names.append(str(n))
            elif isinstance(item, str):
                names.append(item)
        return names

    # ------------------------------------------------------------------ chat
    def ask(self, prompt: Any, *, system: Optional[str] = None, json: bool = False, schema: Any = None,
            temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> Any:
        """One question, one answer: a string; parsed JSON with ``json = true``; JSON checked
        against a shape with ``schema = {...}`` (then ``json`` is implied)."""
        return self.chat([{"role": "user", "content": _text(prompt)}], system=system, json=json, schema=schema,
                         temperature=temperature, max_tokens=max_tokens)

    def chat(self, messages: Union[str, List[Dict[str, Any]]], *, system: Optional[str] = None,
             json: bool = False, schema: Any = None, temperature: Optional[float] = None,
             max_tokens: Optional[int] = None) -> Any:
        """A conversation: ``[{"role": "user", "content": "..."}, ...]``.

        With ``json`` (or a ``schema``) a reply that is not the JSON asked for is sent back to the
        model with what was wrong, ``json_retries`` times (1 by default); then ``llm.FormatError``."""
        if schema is not None:
            _check_schema(schema)
            json = True
        msgs = self._messages(messages, system, json, schema)
        attempt = 0
        while True:
            payload = self._payload(msgs, temperature, max_tokens, stream=False)
            if json and self._json_mode:
                if schema is not None and self._schema_mode:
                    payload["response_format"] = {"type": "json_schema",
                                                  "json_schema": {"name": "answer", "schema": json_schema(schema)}}
                else:
                    payload["response_format"] = {"type": "json_object"}
            data = self._post_chat(payload)
            text = _strip_think(self._content(data))
            if not json:
                return text
            try:
                value = parse_json_reply(text)
                from .prelude import records
                return records(conform(value, schema) if schema is not None else value)
            except FormatError as exc:
                if attempt >= self.json_retries:
                    exc.reply = exc.reply or text
                    raise
                attempt += 1
                shape = f" Shape: {describe_shape(schema)}" if schema is not None else ""
                msgs = msgs + [{"role": "assistant", "content": text},
                               {"role": "user", "content": f"That was not the JSON I asked for ({exc.en}). "
                                                           f"Answer again with the JSON value only.{shape}"}]

    def ask_all(self, prompts: Any, *, system: Optional[str] = None, json: bool = False, schema: Any = None,
                workers: int = 4, errors: str = "raise", temperature: Optional[float] = None,
                max_tokens: Optional[int] = None) -> List[Any]:
        """Many questions at once (``workers`` in parallel); answers come back in the same order.
        ``errors = "null"`` puts null in place of a failed answer instead of stopping."""
        from concurrent.futures import ThreadPoolExecutor
        if errors not in ("raise", "null"):
            raise UpsilError('ask_all: errors is "raise" or "null"', 'ask_all: errors — "raise" или "null"')
        items = list(prompts)
        if schema is not None:
            _check_schema(schema)
        if items and not self._name:
            _ = self.name                      # resolve the model once, not in every thread

        def one(item: Any) -> Any:
            try:
                return self.ask(item, system=system, json=json, schema=schema, temperature=temperature,
                                max_tokens=max_tokens)
            except LLMError:
                if errors == "null":
                    return None
                raise
        from ._progress import Tracker
        from ..i18n import tr
        bar = Tracker(len(items))              # the SOS bar, under `sos run`
        done = [0]
        lock = __import__("threading").Lock()

        def counted(item: Any) -> Any:
            try:
                return one(item)
            finally:
                with lock:
                    done[0] += 1
                    bar.step(done[0], tr(f"answers {done[0]}/{len(items)}", f"ответов {done[0]}/{len(items)}"))
        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
            return list(pool.map(counted, items))

    # ------------------------------------------------------------------ decisions
    def choice(self, prompt: Any, options: Any, *, system: Optional[str] = None) -> Decision:
        """Pick one option (a list, or a dict option → description): a Decision with ``value``,
        ``p`` and ``probs``. ``[m] => text -> choice([...])`` is the same."""
        return self._decide_one(Choice(prompt, options), None, system)

    def yes(self, prompt: Any, *, system: Optional[str] = None) -> float:
        """The probability (0.0–1.0) that the answer to a yes/no question is yes."""
        return self._decide_one(Yes(prompt), None, system)

    def score(self, prompt: Any, levels: Any, *, system: Optional[str] = None) -> Decision:
        """A place on an ordered scale (``0..=3``, ``["low", "high"]``): a Decision with ``mean`` too."""
        return self._decide_one(Score(prompt, levels), None, system)

    def decide(self, state: Any, questions: Any, *, system: Optional[str] = None, workers: int = 4) -> Any:
        """Several questions about one text: ``{"urgent": llm.Yes("..."), "team": llm.Choice("...", [...])}``
        → a record of answers (a probability for Yes, a Decision for Choice and Score)."""
        return _decide_many(self, state, questions, system, workers)

    def _decide_one(self, question: Question, state: Optional[str], system: Optional[str]) -> Any:
        msgs = _decide.build_messages(question, state, system if system is not None else self.system)
        payload: Dict[str, Any] = {"model": self.name, "messages": msgs, "stream": False, "max_tokens": 1,
                                   "temperature": 0, "logprobs": True, "top_logprobs": 20}
        if self._thinking_off and is_loopback(urllib.parse.urlsplit(self.url).hostname):
            # llama.cpp (--jinja) and vLLM: no <think> block before the one-token answer
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        try:
            data = self._request("POST", self.url + "/chat/completions", payload)
        except LLMError as exc:
            if exc.status != 400 or "chat_template_kwargs" not in payload:
                raise
            self._thinking_off = False
            payload.pop("chat_template_kwargs")
            data = self._request("POST", self.url + "/chat/completions", payload)
        count = 2 if question.kind == "yes" else len(question.options)
        probabilities, _ = _decide.letter_probabilities(data, count)
        return _decide.result(question, probabilities)

    def stream(self, prompt: Union[str, List[Dict[str, Any]]], *, system: Optional[str] = None,
               temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> Iterator[str]:
        """The answer piece by piece, as the model writes it."""
        messages = prompt if isinstance(prompt, list) else [{"role": "user", "content": _text(prompt)}]
        payload = self._payload(self._messages(messages, system, False), temperature, max_tokens, stream=True)
        url = self.url + "/chat/completions"
        resp = self._open("POST", url, payload, accept="text/event-stream")
        return self._iter_stream(resp, url)

    def embed(self, texts: Union[str, List[str]], *, model: Optional[str] = None) -> Any:
        """Embedding vectors (``POST /embeddings``): one list of floats per text."""
        single = isinstance(texts, str)
        items = [texts] if single else [_text(t) for t in texts]
        data = self._request("POST", self.url + "/embeddings", {"model": model or self.name, "input": items})
        try:
            rows = sorted(data["data"], key=lambda d: d.get("index", 0))
            vectors = [[float(x) for x in row["embedding"]] for row in rows]
        except (KeyError, TypeError, ValueError):
            raise LLMError("The server's /embeddings reply has no vectors", "Ответ /embeddings не содержит векторов") from None
        if len(vectors) != len(items):
            raise LLMError("The server returned a wrong number of embeddings", "Сервер вернул не то число эмбеддингов")
        return vectors[0] if single else vectors

    # ------------------------------------------------------------------ internals
    def _host(self) -> str:
        return urllib.parse.urlsplit(self.url).netloc or self.url

    def _messages(self, messages: Union[str, List[Dict[str, Any]]], system: Optional[str],
                  json: bool, schema: Any = None) -> List[Dict[str, str]]:
        sys_text = system if system is not None else self.system
        if json:
            sys_text = (sys_text + "\n\n" if sys_text else "") + JSON_INSTRUCTION
            if schema is not None:
                sys_text += f" Shape: {describe_shape(schema)}"
        out: List[Dict[str, str]] = []
        if sys_text:
            out.append({"role": "system", "content": _text(sys_text)})
        if isinstance(messages, str):
            out.append({"role": "user", "content": messages})
            return out
        for m in messages if isinstance(messages, (list, tuple)) else [None]:
            if not isinstance(m, dict) or "role" not in m or "content" not in m:
                raise LLMError('chat() expects a list of {"role": ..., "content": ...}',
                               'chat() ожидает список вида {"role": ..., "content": ...}')
            out.append({"role": str(m["role"]), "content": _text(m["content"])})
        return out

    def _payload(self, messages: List[Dict[str, str]], temperature: Optional[float],
                 max_tokens: Optional[int], stream: bool) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"model": self.name, "messages": messages, "stream": stream}
        t = temperature if temperature is not None else self.temperature
        if t is not None:
            payload["temperature"] = t
        mt = max_tokens if max_tokens is not None else self.max_tokens
        if mt is not None:
            payload["max_tokens"] = int(mt)
        return payload

    def _headers(self, accept: str = "application/json") -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": accept}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _open(self, method: str, url: str, payload: Optional[dict], accept: str = "application/json"):
        body = _json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        deadline = time.monotonic() + self.timeout
        delay = _RETRY_DELAY
        while True:
            try:
                return open_url(method, url, body=body, headers=self._headers(accept), timeout=self.timeout)
            except NetError as exc:
                raise self._net_error(exc) from None
            except HttpError as exc:
                if exc.status == 503 and time.monotonic() + delay < deadline:
                    time.sleep(delay)           # llama.cpp answers 503 while it loads a model
                    delay = min(delay * 2, 8.0)
                    continue
                raise self._http_error(exc) from None

    def _request(self, method: str, url: str, payload: Optional[dict] = None) -> Any:
        resp = self._open(method, url, payload)
        try:
            raw = read_all(resp, url)
        except NetError as exc:
            raise self._net_error(exc) from None
        try:
            return _json.loads(raw.decode("utf-8"))
        except ValueError:
            raise LLMError(f"The server at {self._host()} did not answer with JSON; is it an OpenAI-compatible API?",
                           f"Сервер {self._host()} ответил не в формате JSON; это точно API, совместимый с OpenAI?") from None

    def _post_chat(self, payload: Dict[str, Any]) -> Any:
        while True:
            try:
                return self._request("POST", self.url + "/chat/completions", payload)
            except LLMError as exc:
                fmt = payload.get("response_format")
                if exc.status != 400 or not fmt:
                    raise
                if fmt.get("type") == "json_schema":
                    # no JSON Schema support: plain JSON mode, the shape stays in the prompt
                    self._schema_mode = False
                    payload = {**payload, "response_format": {"type": "json_object"}}
                else:
                    # no JSON mode at all: ask for JSON in words only
                    self._json_mode = False
                    payload = {k: v for k, v in payload.items() if k != "response_format"}

    @staticmethod
    def _content(data: Any) -> str:
        try:
            choice = data["choices"][0]
        except (KeyError, IndexError, TypeError):
            raise LLMError("Unexpected reply from the model server (no choices)",
                           "Неожиданный ответ сервера модели (нет choices)") from None
        message = choice.get("message") or {}
        content = message.get("content") if isinstance(message, dict) else None
        if content is None:
            content = choice.get("text")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return "" if content is None else str(content)

    def _iter_stream(self, resp, url: str) -> Iterator[str]:
        think = _ThinkFilter()
        try:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = _json.loads(data)
                except ValueError:
                    continue
                if isinstance(chunk, dict) and chunk.get("error"):
                    err = chunk["error"]
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    raise LLMError(f"The model stopped with an error: {msg}", f"Модель остановилась с ошибкой: {msg}")
                for choice in (chunk.get("choices") or []) if isinstance(chunk, dict) else []:
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        visible = think.feed(piece)
                        if visible:
                            yield visible
            rest = think.flush()
            if rest:
                yield rest
        except (socket.timeout, TimeoutError):
            raise self._net_error(NetError("timeout", "timed out", url)) from None
        finally:
            resp.close()

    def _net_error(self, exc: NetError) -> LLMError:
        host = self._host()
        if exc.kind == "timeout":
            t = f"{self.timeout:g}"
            return LLMError(f"The model did not answer within {t} s ({host}). A slow model? Try llm.Model(timeout = 300)",
                            f"Модель не ответила за {t} с ({host}). Медленная модель? Попробуйте llm.Model(timeout = 300)")
        if is_loopback(urllib.parse.urlsplit(self.url).hostname):
            return LLMError(f"The local model is not responding ({host}). On SOS: sos models serve",
                            f"Локальная модель не отвечает ({host}). В СОС: sos models serve")
        return LLMError(f"The model server is not responding ({host}): {exc.reason}",
                        f"Сервер модели не отвечает ({host}): {exc.reason}")

    def _http_error(self, exc: HttpError) -> LLMError:
        detail = exc.detail()
        status = exc.status
        if status in (401, 403):
            return LLMError(f"The model server refused the API key (HTTP {status}). Set UPSIL_LLM_KEY or OPENAI_API_KEY",
                            f"Сервер модели не принял ключ API (HTTP {status}). Задайте UPSIL_LLM_KEY или OPENAI_API_KEY",
                            status=status)
        if status == 404:
            return LLMError(f"Not found (HTTP 404): {exc.url}. Is the address an OpenAI-compatible API such as "
                            f"{DEFAULT_URL}? {detail}".rstrip(),
                            f"Не найдено (HTTP 404): {exc.url}. Адрес точно API, совместимый с OpenAI, "
                            f"вроде {DEFAULT_URL}? {detail}".rstrip(), status=status)
        return LLMError(f"The model server answered HTTP {status}: {detail}",
                        f"Сервер модели ответил HTTP {status}: {detail}", status=status)


def models() -> List[str]:
    """Names of the models on the default server."""
    return Model().models()


def _decide_many(model: Any, state: Any, questions: Any, system: Optional[str], workers: int) -> Any:
    from concurrent.futures import ThreadPoolExecutor
    from .prelude import Record, show
    if not isinstance(questions, dict) or not questions:
        raise UpsilError('decide: the questions are a dict {"name": llm.Yes("..."), ...}',
                         'decide: вопросы — словарь {"имя": llm.Yes("..."), ...}')
    for key, q in questions.items():
        if not isinstance(q, Question):
            raise UpsilError(f"decide: {show(key)} is not a question (llm.Yes, llm.Choice or llm.Score)",
                             f"decide: {show(key)} — не вопрос (llm.Yes, llm.Choice или llm.Score)")
    if isinstance(model, Model) and not model._name:
        _ = model.name                         # resolve the model once, not in every thread
    text = show(state)
    items = list(questions.items())
    with ThreadPoolExecutor(max_workers=max(1, min(int(workers), len(items)))) as pool:
        answers = list(pool.map(lambda kv: model._decide_one(kv[1], text, system), items))
    return Record((k, a) for (k, _), a in zip(items, answers))


class SystemOne:
    """Decisions from a server that speaks the ``/v1/systemone`` protocol: Jev by TypeSafe
    (``https://api.typesafe.ai``, a key in ``TYPESAFE_API_KEY``) or an open one such as Kev.
    It answers ``-> choice``, ``-> yes``, ``-> score`` and ``decide``; it does not write text."""

    def __init__(self, url: Optional[str] = None, *, api_key: Optional[str] = None, model: str = "jev-latest",
                 timeout: Optional[float] = None, system: Optional[str] = None):
        base = (url or os.environ.get("UPSIL_SYSTEMONE_URL") or "https://api.typesafe.ai").rstrip("/")
        if base.endswith("/v1/systemone"):
            base = base[:-len("/v1/systemone")]
        elif base.endswith("/v1"):
            base = base[:-3]
        self.url = base
        self.api_key = api_key or os.environ.get("UPSIL_SYSTEMONE_KEY") or os.environ.get("TYPESAFE_API_KEY") or None
        self.model = model
        self.timeout = float(timeout) if timeout else 30.0
        self.system = system

    def __repr__(self) -> str:
        return f'llm.SystemOne("{self.url}", model="{self.model}")'

    __str__ = __repr__

    def choice(self, prompt: Any, options: Any, *, system: Optional[str] = None) -> Decision:
        return self._decide_one(Choice(prompt, options), None, system)

    def yes(self, prompt: Any, *, system: Optional[str] = None) -> float:
        return self._decide_one(Yes(prompt), None, system)

    def score(self, prompt: Any, levels: Any, *, system: Optional[str] = None) -> Decision:
        return self._decide_one(Score(prompt, levels), None, system)

    def decide(self, state: Any, questions: Any, *, system: Optional[str] = None, workers: int = 4) -> Any:
        """All the questions go in one request, as the protocol intends."""
        from .prelude import Record, show
        if not isinstance(questions, dict) or not questions:
            raise UpsilError('decide: the questions are a dict {"name": llm.Yes("..."), ...}',
                             'decide: вопросы — словарь {"имя": llm.Yes("..."), ...}')
        sys_text = system if system is not None else self.system
        body_questions = {}
        for key, q in questions.items():
            if not isinstance(q, Question):
                raise UpsilError(f"decide: {show(key)} is not a question (llm.Yes, llm.Choice or llm.Score)",
                                 f"decide: {show(key)} — не вопрос (llm.Yes, llm.Choice или llm.Score)")
            body_questions[show(key)] = _decide.systemone_question(q, sys_text)
        answers = self._post(show(state), body_questions)
        out = []
        for key, q in questions.items():
            if show(key) not in answers:
                raise LLMError(f"/v1/systemone did not answer {show(key)!r}", f"/v1/systemone не ответил на {show(key)!r}")
            out.append((key, _decide.systemone_result(q, answers[show(key)])))
        return Record(out)

    def _decide_one(self, question: Question, state: Optional[str], system: Optional[str]) -> Any:
        sys_text = system if system is not None else self.system
        if state is None:        # one text holds both: the state is the text, the question points at it
            state, question = question.text, Question(question.kind, "Answer the question in the text.",
                                                      None if question.kind == "yes" else
                                                      dict(zip(question.options, question.descriptions)))
        answers = self._post(state, {"q": _decide.systemone_question(question, sys_text)})
        if "q" not in answers:
            raise LLMError("/v1/systemone gave no answer", "/v1/systemone не дал ответа")
        return _decide.systemone_result(question, answers["q"])

    def _post(self, state: str, questions: Dict[str, Any]) -> Dict[str, Any]:
        url = self.url + "/v1/systemone"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = _json.dumps({"model": self.model, "state": state, "questions": questions},
                           ensure_ascii=False).encode("utf-8")
        host = urllib.parse.urlsplit(self.url).netloc or self.url
        deadline = time.monotonic() + self.timeout
        delay = _RETRY_DELAY
        while True:
            try:
                resp = open_url("POST", url, body=body, headers=headers, timeout=self.timeout)
                data = _json.loads(read_all(resp, url).decode("utf-8"))
                break
            except NetError as exc:
                raise LLMError(f"The decision server is not responding ({host}): {exc.reason}",
                               f"Сервер решений не отвечает ({host}): {exc.reason}") from None
            except ValueError:
                raise LLMError(f"The decision server at {host} did not answer with JSON",
                               f"Сервер решений {host} ответил не в формате JSON") from None
            except HttpError as exc:
                if exc.status in (429, 529, 503) and time.monotonic() + delay < deadline:
                    time.sleep(delay)          # rate limited or overloaded: back off and retry
                    delay = min(delay * 2, 8.0)
                    continue
                if exc.status in (401, 403):
                    raise LLMError(f"The decision server refused the API key (HTTP {exc.status}). "
                                   f"Set TYPESAFE_API_KEY or UPSIL_SYSTEMONE_KEY",
                                   f"Сервер решений не принял ключ API (HTTP {exc.status}). "
                                   f"Задайте TYPESAFE_API_KEY или UPSIL_SYSTEMONE_KEY", status=exc.status) from None
                raise LLMError(f"The decision server answered HTTP {exc.status}: {exc.detail()}",
                               f"Сервер решений ответил HTTP {exc.status}: {exc.detail()}", status=exc.status) from None
        answers = data.get("answers") if isinstance(data, dict) else None
        if not isinstance(answers, dict):
            raise LLMError("The /v1/systemone reply has no answers", "В ответе /v1/systemone нет answers")
        return answers
