# SPDX-License-Identifier: Apache-2.0
"""http: simple HTTP requests.

    import http
    val page = http.get("https://example.org")
    val data = http.get_json("https://api.github.com/repos/svoya-os/upsil")
    val reply = http.post_json("http://127.0.0.1:8000/api", {"q": "hi"})

Errors (no connection, HTTP 4xx/5xx) stop the program with a clear message.
Proxies from the environment are used, except for local addresses.
"""

from __future__ import annotations

import json as _json
import urllib.parse
from typing import Any, Dict, Optional

from ..errors import UpsilError
from ._net import HttpError, NetError, open_url, read_all

__all__ = ["get", "get_json", "post", "post_json"]


def _request(method: str, url: str, body: Optional[bytes], headers: Optional[Dict[str, str]],
             timeout: float) -> bytes:
    host = urllib.parse.urlsplit(url).netloc or url
    try:
        return read_all(open_url(method, url, body=body, headers=headers, timeout=float(timeout)), url)
    except HttpError as exc:
        detail = exc.detail()
        raise UpsilError(f"HTTP {exc.status} from {url}: {detail}".rstrip(": "),
                         f"HTTP {exc.status} от {url}: {detail}".rstrip(": ")) from None
    except NetError as exc:
        if exc.kind == "timeout":
            raise UpsilError(f"{host} did not answer within {timeout:g} s", f"{host} не ответил за {timeout:g} с") from None
        raise UpsilError(f"Cannot reach {host}: {exc.reason}", f"Не удаётся связаться с {host}: {exc.reason}") from None


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", "replace")


def get(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 30) -> str:
    """The body of the page as text."""
    return _decode(_request("GET", url, None, headers, timeout))


def get_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 30) -> Any:
    hdrs = {"Accept": "application/json", **(headers or {})}
    return _json.loads(_decode(_request("GET", url, None, hdrs, timeout)))


def post(url: str, body: str = "", headers: Optional[Dict[str, str]] = None, timeout: float = 30) -> str:
    hdrs = {"Content-Type": "text/plain; charset=utf-8", **(headers or {})}
    return _decode(_request("POST", url, str(body).encode("utf-8"), hdrs, timeout))


def post_json(url: str, data: Any, headers: Optional[Dict[str, str]] = None, timeout: float = 30) -> Any:
    """Send ``data`` as JSON; returns the parsed JSON answer (or the text if it is not JSON)."""
    hdrs = {"Content-Type": "application/json", "Accept": "application/json", **(headers or {})}
    text = _decode(_request("POST", url, _json.dumps(data, ensure_ascii=False).encode("utf-8"), hdrs, timeout))
    try:
        return _json.loads(text)
    except ValueError:
        return text
