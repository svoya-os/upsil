# SPDX-License-Identifier: Apache-2.0
"""time: clocks, pauses and dates.

    import time
    val t0 = time.monotonic()
    time.sleep(0.5)
    print("took {time.monotonic() - t0:.1f} s on {time.today()}")
"""

from __future__ import annotations

import time as _time
from datetime import datetime as _datetime
from typing import Optional

__all__ = ["now", "monotonic", "sleep", "today", "format"]


def now() -> float:
    """Seconds since 1970-01-01 UTC."""
    return _time.time()


def monotonic() -> float:
    """A clock for measuring durations (never goes back)."""
    return _time.monotonic()


def sleep(seconds: float) -> None:
    _time.sleep(float(seconds))


def today() -> str:
    """Today's local date as YYYY-MM-DD."""
    return _datetime.now().strftime("%Y-%m-%d")


def format(fmt: str = "%Y-%m-%d %H:%M:%S", at: Optional[float] = None) -> str:  # noqa: A001 - UpsiL name
    """Local time (now, or ``at`` seconds since 1970) formatted with strftime codes."""
    moment = _datetime.now() if at is None else _datetime.fromtimestamp(float(at))
    return moment.strftime(fmt)
