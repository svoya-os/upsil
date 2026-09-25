# SPDX-License-Identifier: Apache-2.0
"""llm: talk to a language model over an OpenAI-compatible HTTP API.

    import llm
    llm m = llm.Model("qwen3.5-4b")
    print([m] => "Say hi")                  // the prompt operator calls m.ask
    for (piece in m.stream("Tell a story")) { print(piece, end = "") }

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
from . import config as _config
from ._net import HttpError, NetError, is_loopback, open_url, read_all

__all__ = ["Model", "LLMError", "models", "default_url"]

DEFAULT_URL = "http://127.0.0.1:8080/v1"
DEFAULT_TIMEOUT = 120.0
JSON_INSTRUCTION = "Answer with one valid JSON value only: no explanations, no code fences."
_RETRY_DELAY = 1.0          # seconds, doubled per retry while the server loads a model (HTTP 503)


class LLMError(UpsilError):
    """A model call failed; ``status`` is the HTTP status when there was one."""

    def __init__(self, en: str, ru: Optional[str] = None, *, status: Optional[int] = None):
        super().__init__(en, ru)
        self.status = status


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
    raise LLMError(f"The model's reply is not valid JSON: {short!r}",
                   f"Ответ модели — не JSON: {short!r}")


class Model:
    """A chat model on an OpenAI-compatible server. Nothing is sent until the first call."""

    def __init__(self, name: Optional[str] = None, *, url: Optional[str] = None, api_key: Optional[str] = None,
                 timeout: Optional[float] = None, temperature: Optional[float] = None,
                 max_tokens: Optional[int] = None, system: Optional[str] = None):
        self.url = (url or default_url()).rstrip("/")
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
    def ask(self, prompt: Any, *, system: Optional[str] = None, json: bool = False,
            temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> Any:
        """One question, one answer (a string; parsed JSON with ``json = true``)."""
        return self.chat([{"role": "user", "content": _text(prompt)}], system=system, json=json,
                         temperature=temperature, max_tokens=max_tokens)

    def chat(self, messages: Union[str, List[Dict[str, Any]]], *, system: Optional[str] = None,
             json: bool = False, temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> Any:
        """A conversation: ``[{"role": "user", "content": "..."}, ...]``."""
        payload = self._payload(self._messages(messages, system, json), temperature, max_tokens, stream=False)
        if json and self._json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = self._post_chat(payload)
        text = _strip_think(self._content(data))
        return parse_json_reply(text) if json else text

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
                  json: bool) -> List[Dict[str, str]]:
        sys_text = system if system is not None else self.system
        if json:
            sys_text = (sys_text + "\n\n" if sys_text else "") + JSON_INSTRUCTION
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
        try:
            return self._request("POST", self.url + "/chat/completions", payload)
        except LLMError as exc:
            if exc.status == 400 and "response_format" in payload:
                # the server has no JSON mode: ask for JSON in words only
                self._json_mode = False
                payload = {k: v for k, v in payload.items() if k != "response_format"}
                return self._request("POST", self.url + "/chat/completions", payload)
            raise

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
