# SPDX-License-Identifier: Apache-2.0
"""HTTP for the runtime (urllib only).

Local servers (127.0.0.1, localhost, ::1) are always reached directly, even
when HTTP(S)_PROXY is set; other hosts use the proxy settings of the
environment, like any urllib program.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Optional

from .. import __version__

USER_AGENT = f"upsil/{__version__}"
MAX_ERROR_BODY = 64 * 1024


class HttpError(Exception):
    """The server answered with an HTTP error status."""

    def __init__(self, status: int, body: bytes, url: str):
        super().__init__(f"HTTP {status} for {url}")
        self.status = status
        self.body = body
        self.url = url

    def detail(self) -> str:
        """The server's error message, if it sent one."""
        text = self.body.decode("utf-8", "replace").strip()
        try:
            import json
            data = json.loads(text)
        except ValueError:
            return text[:300]
        if isinstance(data, dict):
            err = data.get("error", data.get("message", data.get("detail")))
            if isinstance(err, dict):
                err = err.get("message") or err.get("type") or err
            if err:
                return str(err)[:300]
        return text[:300]


class NetError(Exception):
    """The server could not be reached (kind "connect") or did not answer in time ("timeout")."""

    def __init__(self, kind: str, reason: str, url: str):
        super().__init__(f"{kind}: {reason}")
        self.kind = kind
        self.reason = reason
        self.url = url


def is_loopback(host: Optional[str]) -> bool:
    if not host:
        return False
    if host in ("localhost", "localhost.localdomain") or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def open_url(method: str, url: str, *, body: Optional[bytes] = None,
             headers: Optional[Dict[str, str]] = None, timeout: float = 30.0):
    """Open a URL; returns the response (use it as a context manager)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise NetError("connect", f"unsupported URL {url!r}", url)
    hdrs = {"User-Agent": USER_AGENT}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    handlers = [urllib.request.ProxyHandler({})] if is_loopback(parts.hostname) else []
    opener = urllib.request.build_opener(*handlers)
    try:
        return opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        try:
            data = exc.read(MAX_ERROR_BODY)
        except Exception:
            data = b""
        finally:
            exc.close()
        raise HttpError(exc.code, data, url) from None
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise NetError("timeout", "timed out", url) from None
        text = getattr(reason, "strerror", None) or str(reason)
        raise NetError("connect", text, url) from None
    except (socket.timeout, TimeoutError):
        raise NetError("timeout", "timed out", url) from None
    except (OSError, http.client.HTTPException) as exc:
        raise NetError("connect", getattr(exc, "strerror", None) or exc.__class__.__name__, url) from None


def read_all(resp, url: str) -> bytes:
    try:
        with resp:
            return resp.read()
    except (socket.timeout, TimeoutError):
        raise NetError("timeout", "timed out", url) from None
    except (OSError, http.client.HTTPException) as exc:
        raise NetError("connect", getattr(exc, "strerror", None) or exc.__class__.__name__, url) from None
