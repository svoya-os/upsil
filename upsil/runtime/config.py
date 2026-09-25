# SPDX-License-Identifier: Apache-2.0
"""User settings from ``~/.config/upsil/config.toml``.

    [llm]
    url = "http://127.0.0.1:8080/v1"   # any OpenAI-compatible endpoint
    model = "qwen3.5-4b"               # default: the first model the server lists
    timeout = 120                      # seconds

    [rag]
    embed_model = "bge-m3"             # default: the llm model
    backend = "auto"                   # auto | embeddings | bm25

``UPSIL_CONFIG`` points to another file; ``XDG_CONFIG_HOME`` is respected.
Python 3.11+ reads the file with ``tomllib``; on 3.10 a small parser handles
the subset above (tables, strings, numbers, booleans, flat arrays).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Tuple

from ..errors import UpsilError

_cache: Dict[Tuple[str, int, int], Dict[str, Any]] = {}


def config_path() -> Path:
    explicit = os.environ.get("UPSIL_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "upsil" / "config.toml"


def load() -> Dict[str, Any]:
    path = config_path()
    try:
        if not path.is_file():
            return {}
        st = path.stat()
    except OSError:
        return {}
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key not in _cache:
        text = path.read_text(encoding="utf-8")
        _cache.clear()
        _cache[key] = parse_toml(text, str(path))
    return _cache[key]


def get(section: str, key: str, default: Any = None) -> Any:
    table = load().get(section)
    if isinstance(table, dict):
        value = table.get(key, default)
        return default if value == "" else value
    return default


def parse_toml(text: str, filename: str = "config.toml") -> Dict[str, Any]:
    try:
        import tomllib  # Python 3.11+
    except ImportError:  # pragma: no cover - exercised on Python 3.10
        return parse_toml_subset(text, filename)
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise UpsilError(f"{filename}: bad settings file: {exc}",
                         f"{filename}: ошибка в файле настроек: {exc}") from None


# ---------------------------------------------------------------------- TOML subset (Python 3.10)

_KEY_RE = re.compile(r'^(?P<key>[A-Za-z0-9_-]+|"[^"]*")\s*=\s*(?P<value>.*)$')
_INT_RE = re.compile(r"^[+-]?\d(_?\d)*$")
_FLOAT_RE = re.compile(r"^[+-]?\d(_?\d)*(\.\d(_?\d)*)?([eE][+-]?\d(_?\d)*)?$")


def _bad(filename: str, lineno: int, en: str, ru: str) -> UpsilError:
    return UpsilError(f"{filename}:{lineno}: bad settings file: {en}", f"{filename}:{lineno}: ошибка в файле настроек: {ru}")


def _strip_comment(line: str) -> str:
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return line[:i]
        i += 1
    return line


def _split_array(inner: str) -> list:
    items, buf, quote = [], [], None
    i = 0
    while i < len(inner):
        ch = inner[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(inner):
                buf.append(inner[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            items.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    last = "".join(buf).strip()
    if last:
        items.append(last)
    return items


def _value(text: str, filename: str, lineno: int) -> Any:
    s = text.strip()
    if s.startswith('"'):
        if len(s) < 2 or not s.endswith('"'):
            raise _bad(filename, lineno, "unterminated string", "незакрытая строка")
        try:
            return json.loads(s)
        except ValueError:
            raise _bad(filename, lineno, f"bad string {s}", f"неверная строка {s}") from None
    if s.startswith("'"):
        if len(s) < 2 or not s.endswith("'"):
            raise _bad(filename, lineno, "unterminated string", "незакрытая строка")
        return s[1:-1]
    if s in ("true", "false"):
        return s == "true"
    if s.startswith("["):
        if not s.endswith("]"):
            raise _bad(filename, lineno, "arrays must fit on one line", "массив должен помещаться на одной строке")
        return [_value(item, filename, lineno) for item in _split_array(s[1:-1])]
    if _INT_RE.match(s):
        return int(s.replace("_", ""))
    if _FLOAT_RE.match(s):
        return float(s.replace("_", ""))
    raise _bad(filename, lineno, f"unsupported value {s!r}", f"неподдерживаемое значение {s!r}")


def parse_toml_subset(text: str, filename: str = "config.toml") -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    table = data
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("["):
            if line.startswith("[[") or not line.endswith("]"):
                raise _bad(filename, lineno, "unsupported table header", "неподдерживаемый заголовок таблицы")
            table = data
            for part in line[1:-1].split("."):
                name = part.strip().strip('"')
                nxt = table.setdefault(name, {})
                if not isinstance(nxt, dict):
                    raise _bad(filename, lineno, f"'{name}' is not a table", f"'{name}' — не таблица")
                table = nxt
            continue
        m = _KEY_RE.match(line)
        if not m:
            raise _bad(filename, lineno, f"expected key = value, got {line!r}",
                       f"ожидалось ключ = значение, а встретилось {line!r}")
        table[m.group("key").strip('"')] = _value(m.group("value"), filename, lineno)
    return data
