# SPDX-License-Identifier: Apache-2.0
"""A tiny OpenAI-compatible server for tests (threading http.server, 127.0.0.1).

Replies are deterministic: "echo: <last user message>" (or JSON when the
request asks for JSON). Embeddings are bag-of-words vectors, so texts that
share words are close. With ``logprobs`` requested, the reply is one token and
the top logprobs come from ``decide(body)`` ({token: probability}); POST
/v1/systemone answers with ``systemone(body)`` (the "answers" object).
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional

DIM = 64


def bow_vector(text: str) -> List[float]:
    vec = [0.0] * DIM
    for word in re.findall(r"\w+", text.lower()):
        vec[zlib.crc32(word.encode("utf-8")) % DIM] += 1.0
    return vec


class MockOpenAI:
    def __init__(self, *, models=("mock-small", "mock-embed"), embeddings: bool = True, json_mode: bool = True,
                 fail_503: int = 0, require_key: Optional[str] = None, think: bool = False, delay: float = 0.0,
                 reply: Optional[Callable[[Dict[str, Any]], str]] = None,
                 decide: Optional[Callable[[Dict[str, Any]], Dict[str, float]]] = None, logprobs: bool = True,
                 template_kwargs: bool = True,
                 systemone: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None):
        self.models = list(models)
        self.embeddings = embeddings
        self.json_mode = json_mode
        self.fail_503 = fail_503
        self.require_key = require_key
        self.think = think
        self.delay = delay
        self.reply = reply
        self.decide = decide
        self.logprobs = logprobs                 # False: a server that ignores the logprobs request
        self.template_kwargs = template_kwargs   # False: HTTP 400 for chat_template_kwargs
        self.systemone = systemone
        self.requests: List[Dict[str, Any]] = []
        self._server: Optional[ThreadingHTTPServer] = None

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> "MockOpenAI":
        mock = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                pass

            def _send(self, status: int, payload: Any, content_type: str = "application/json") -> None:
                body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                mock.requests.append({"method": "GET", "path": self.path, "headers": dict(self.headers), "body": None})
                if self.path == "/v1/models":
                    self._send(200, {"object": "list", "data": [{"id": m, "object": "model"} for m in mock.models]})
                else:
                    self._send(404, {"error": {"message": f"no route {self.path}"}})

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw.decode("utf-8")) if raw else {}
                except ValueError:
                    body = {}
                mock.requests.append({"method": "POST", "path": self.path, "headers": dict(self.headers), "body": body})
                if mock.require_key and self.headers.get("Authorization") != f"Bearer {mock.require_key}":
                    return self._send(401, {"error": {"message": "Invalid API key"}})
                if self.path == "/v1/chat/completions":
                    return self.chat(body)
                if self.path == "/v1/embeddings":
                    return self.embed(body)
                if self.path == "/v1/systemone" and mock.systemone is not None:
                    return self._send(200, {"model": "mock-jev", "answers": mock.systemone(body),
                                            "usage": {"input_tokens": 10, "output_tokens": 1}})
                self._send(404, {"error": {"message": f"no route {self.path}"}})

            def chat(self, body: Dict[str, Any]) -> None:
                if mock.delay:
                    time.sleep(mock.delay)
                if mock.fail_503 > 0:
                    mock.fail_503 -= 1
                    return self._send(503, {"error": {"message": "Loading model", "code": 503}})
                if "response_format" in body and not mock.json_mode:
                    return self._send(400, {"error": {"message": "response_format is not supported"}})
                if "chat_template_kwargs" in body and not mock.template_kwargs:
                    return self._send(400, {"error": {"message": "Unrecognized request argument: chat_template_kwargs"}})
                if body.get("logprobs"):
                    return self.one_token(body)
                reply = mock.make_reply(body)
                if body.get("stream"):
                    return self.stream(reply)
                self._send(200, {"id": "chatcmpl-1", "object": "chat.completion", "model": body.get("model"),
                                 "choices": [{"index": 0, "finish_reason": "stop",
                                              "message": {"role": "assistant", "content": reply}}]})

            def one_token(self, body: Dict[str, Any]) -> None:
                probs = mock.decide(body) if mock.decide else mock.default_decision(body)
                ranked = sorted(probs.items(), key=lambda kv: -kv[1])
                top = [{"token": t, "logprob": math.log(p) if p > 0 else -1e9, "bytes": list(t.encode("utf-8"))}
                       for t, p in ranked[:int(body.get("top_logprobs") or 1)]]
                choice: Dict[str, Any] = {"index": 0, "finish_reason": "length",
                                          "message": {"role": "assistant", "content": ranked[0][0]}}
                if mock.logprobs:
                    choice["logprobs"] = {"content": [{"token": ranked[0][0], "logprob": top[0]["logprob"],
                                                       "top_logprobs": top}]}
                self._send(200, {"id": "chatcmpl-1", "object": "chat.completion", "model": body.get("model"),
                                 "choices": [choice]})

            def stream(self, reply: str) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                pieces = [reply[i:i + 4] for i in range(0, len(reply), 4)]
                for piece in pieces:
                    chunk = {"choices": [{"index": 0, "delta": {"content": piece}}]}
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.close_connection = True

            def embed(self, body: Dict[str, Any]) -> None:
                if not mock.embeddings:
                    return self._send(501, {"error": {"code": 501, "type": "not_supported_error",
                                                      "message": "This server does not support embeddings. "
                                                                 "Start it with `--embeddings`"}})
                inputs = body.get("input")
                inputs = [inputs] if isinstance(inputs, str) else list(inputs or [])
                self._send(200, {"object": "list", "model": body.get("model"),
                                 "data": [{"object": "embedding", "index": i, "embedding": bow_vector(t)}
                                          for i, t in enumerate(inputs)]})

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request: Any, client_address: Any) -> None:
                pass   # a client that timed out and hung up is expected in tests

        self._server = Server(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self) -> "MockOpenAI":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    # ------------------------------------------------------------------ replies
    def make_reply(self, body: Dict[str, Any]) -> str:
        if self.reply is not None:
            return self.reply(body)
        messages = body.get("messages") or []
        last = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        system = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
        if "JSON" in system:
            text = "```json\n" + json.dumps({"echo": last}, ensure_ascii=False) + "\n```"
        else:
            text = f"echo: {last}"
        if self.think:
            text = "<think>let me think about it</think>\n\n" + text
        return text

    @staticmethod
    def default_decision(body: Dict[str, Any]) -> Dict[str, float]:
        """The first option is likely (0.7), the second less (0.2), the rest share 0.1."""
        text = (body.get("messages") or [{}])[-1].get("content", "")
        letters = re.findall(r"^([A-Z])\. ", text, re.M)
        probs = {letters[0]: 0.7, letters[1]: 0.2} if len(letters) >= 2 else {"A": 1.0}
        rest = letters[2:]
        for letter in rest:
            probs[letter] = 0.1 / len(rest)
        if not rest and len(letters) >= 2:
            probs[letters[1]] += 0.1
        return probs

    def chat_requests(self) -> List[Dict[str, Any]]:
        return [r for r in self.requests if r["path"] == "/v1/chat/completions"]


def free_port() -> int:
    """A local port with nothing listening on it."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
