# SPDX-License-Identifier: Apache-2.0
"""Progress for the SOS bar: `sos run` gives a program a job file (``SVOYA_JOB_FILE``, schema v1 of
SOS's cli/svoya_cli/jobs.py) and shows its progress in the bar. Outside of it nothing happens.

Writes are atomic (a temporary file, then rename) and at most a few per second.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Optional

_last = [0.0]
_MIN_INTERVAL = 0.3


def report(fraction: float, message: Optional[str] = None, eta_sec: Optional[float] = None,
           force: bool = False) -> bool:
    """Update the job file; returns true when there is one (the program runs under `sos run`)."""
    path = os.environ.get("SVOYA_JOB_FILE")
    if not path:
        return False
    now = time.monotonic()
    if not force and now - _last[0] < _MIN_INTERVAL and fraction < 1.0:
        return True
    _last[0] = now
    try:
        with open(path, encoding="utf-8") as f:
            job = json.load(f)
    except (OSError, ValueError):
        return False
    job["progress"] = max(0.0, min(1.0, float(fraction)))
    job["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if message is not None:
        job["message"] = str(message)[:120]
    if eta_sec is not None:
        job["etaSec"] = max(0, int(eta_sec))
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        return False
    return True


class Tracker:
    """Progress of ``total`` steps with an ETA from the time taken so far."""

    def __init__(self, total: int) -> None:
        self.total = max(1, int(total))
        self.started = time.monotonic()

    def step(self, done: int, message: Optional[str] = None) -> None:
        elapsed = time.monotonic() - self.started
        eta = elapsed / done * (self.total - done) if done else None
        report(done / self.total, message, eta, force=done >= self.total)
