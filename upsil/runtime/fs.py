# SPDX-License-Identifier: Apache-2.0
"""fs: files and folders. Text is always UTF-8.

    import fs
    fs.write("notes/todo.md", "- buy milk\n")
    for (name in fs.list("notes", "*.md")) { print(name, len(fs.read(fs.join("notes", name)))) }
"""

from __future__ import annotations

import builtins as _builtins
import os as _os
from pathlib import Path as _Path
from typing import List

__all__ = ["read", "write", "append", "lines", "exists", "is_file", "is_dir", "list", "mkdir", "remove",
           "join", "dirname", "basename", "home", "cwd"]


def read(path: str) -> str:
    """The whole file as text."""
    return _Path(path).expanduser().read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    """Replace the file's contents (the folder must exist)."""
    _Path(path).expanduser().write_text(str(text), encoding="utf-8")


def append(path: str, text: str) -> None:
    with open(_Path(path).expanduser(), "a", encoding="utf-8") as f:
        f.write(str(text))


def lines(path: str) -> List[str]:
    """The lines of a text file, without line breaks."""
    return read(path).splitlines()


def exists(path: str) -> bool:
    return _Path(path).expanduser().exists()


def is_file(path: str) -> bool:
    return _Path(path).expanduser().is_file()


def is_dir(path: str) -> bool:
    return _Path(path).expanduser().is_dir()


def list(path: str = ".", glob: str = "*") -> List[str]:  # noqa: A001 - UpsiL name
    """Sorted paths under ``path`` that match ``glob``, relative to ``path``
    (``"**/*.md"`` searches subfolders too)."""
    root = _Path(path).expanduser()
    return sorted(p.relative_to(root).as_posix() for p in root.glob(glob))


def mkdir(path: str) -> None:
    """Create a folder (and its parents); fine if it already exists."""
    _Path(path).expanduser().mkdir(parents=True, exist_ok=True)


def remove(path: str) -> None:
    """Delete a file (not a folder)."""
    _os.remove(_Path(path).expanduser())


def join(*parts: str) -> str:
    return _os.path.join(*[_builtins.str(p) for p in parts])


def dirname(path: str) -> str:
    """The folder part of a path: ``fs.dirname("a/b.md") == "a"``."""
    return _os.path.dirname(str(path))


def basename(path: str) -> str:
    """The last part of a path: ``fs.basename("a/b.md") == "b.md"``."""
    return _os.path.basename(str(path))


def home() -> str:
    return _os.path.expanduser("~")


def cwd() -> str:
    return _os.getcwd()
