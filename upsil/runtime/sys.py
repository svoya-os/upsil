# SPDX-License-Identifier: Apache-2.0
"""sys: program arguments, environment variables, exit.

    import sys
    if len(sys.args) == 0 { print("usage: upsil run tool.upl FILE")
                            sys.exit(64) }
    val home = sys.env("HOME", "/tmp")

``sys.args`` are the words after the file name in ``upsil run file.upl a b``
(here ``["a", "b"]``); ``sys.script`` is the file name. ``sys.progress(0.5, "шаг 5 из 10")``
shows progress in the SOS bar when the program runs under ``sos run`` (and does nothing
elsewhere).
"""

from __future__ import annotations

import os as _os
import sys as _sys
from typing import Any, Optional

from .. import __version__

__all__ = ["args", "script", "env", "exit", "platform", "version", "progress"]

version = __version__
platform = _sys.platform


def env(name: str, default: Optional[str] = None) -> Optional[str]:
    return _os.environ.get(name, default)


def exit(code: int = 0) -> None:  # noqa: A001 - UpsiL name
    raise SystemExit(code)


def progress(fraction: float, message: Optional[str] = None, eta: Optional[float] = None) -> bool:
    """Progress 0.0–1.0 (and a short message, an ETA in seconds) for the SOS bar under `sos run`;
    returns true when it was shown there."""
    from ._progress import report
    return report(float(fraction), None if message is None else str(message), eta, force=True)


def __getattr__(name: str) -> Any:
    if name == "args":
        return list(_sys.argv[1:])
    if name == "script":
        return _sys.argv[0] if _sys.argv else ""
    raise AttributeError(name)
