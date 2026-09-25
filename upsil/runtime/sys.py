# SPDX-License-Identifier: Apache-2.0
"""sys: program arguments, environment variables, exit.

    import sys
    if len(sys.args) == 0 { print("usage: upsil run tool.upl FILE")
                            sys.exit(64) }
    val home = sys.env("HOME", "/tmp")

``sys.args`` are the words after the file name in ``upsil run file.upl a b``
(here ``["a", "b"]``); ``sys.script`` is the file name.
"""

from __future__ import annotations

import os as _os
import sys as _sys
from typing import Any, Optional

from .. import __version__

__all__ = ["args", "script", "env", "exit", "platform", "version"]

version = __version__
platform = _sys.platform


def env(name: str, default: Optional[str] = None) -> Optional[str]:
    return _os.environ.get(name, default)


def exit(code: int = 0) -> None:  # noqa: A001 - UpsiL name
    raise SystemExit(code)


def __getattr__(name: str) -> Any:
    if name == "args":
        return list(_sys.argv[1:])
    if name == "script":
        return _sys.argv[0] if _sys.argv else ""
    raise AttributeError(name)
