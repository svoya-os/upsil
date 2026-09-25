# SPDX-License-Identifier: Apache-2.0
"""csv: tables in text files (UTF-8).

    import csv
    val rows = csv.read("reviews.csv")                  // [{"text": "...", "stars": "5"}, ...]
    val nums = csv.read("scores.csv", numbers = true)   // "5" -> 5, "0.9" -> 0.9
    csv.write("out.csv", [{"text": "ok", "label": "pos"}])

The first row names the columns: each row becomes a dict. ``header = false`` gives lists.
"""

from __future__ import annotations

import csv as _csv
import io as _io
from pathlib import Path as _Path
from typing import Any, List, Optional

from ..errors import UpsilError

__all__ = ["read", "parse", "write", "stringify"]


def _number(value: str) -> Any:
    text = value.strip()
    if not text:
        return value
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text.replace(",", ".")) if text.count(",") <= 1 and "." not in text else float(text)
    except ValueError:
        return value


def parse(text: str, sep: str = ",", header: bool = True, numbers: bool = False) -> List[Any]:
    """Rows of CSV text: dicts by the header row, or lists with ``header = false``."""
    rows = list(_csv.reader(_io.StringIO(text), delimiter=sep))
    rows = [r for r in rows if r]
    if numbers:
        rows = [rows[0]] + [[_number(v) for v in r] for r in rows[1:]] if header and rows else \
            [[_number(v) for v in r] for r in rows]
    if not header:
        return rows
    if not rows:
        return []
    names = [str(n).strip() for n in rows[0]]
    return [dict(zip(names, r + [None] * (len(names) - len(r)))) for r in rows[1:]]


def read(path: str, sep: str = ",", header: bool = True, numbers: bool = False) -> List[Any]:
    """The rows of a CSV file (a byte-order mark at the start is ignored)."""
    text = _Path(path).expanduser().read_text(encoding="utf-8-sig")
    return parse(text, sep=sep, header=header, numbers=numbers)


def stringify(rows: List[Any], columns: Optional[List[str]] = None, sep: str = ",") -> str:
    """CSV text: dict rows get a header (``columns`` or the keys of all rows, in order), lists are written as is."""
    out = _io.StringIO()
    writer = _csv.writer(out, delimiter=sep, lineterminator="\n")
    rows = list(rows)
    if rows and all(isinstance(r, dict) for r in rows):
        if columns is None:
            columns = []
            for r in rows:
                for k in r:
                    if k not in columns:
                        columns.append(k)
        writer.writerow(columns)
        for r in rows:
            writer.writerow(["" if r.get(c) is None else _cell(r.get(c)) for c in columns])
        return out.getvalue()
    if any(isinstance(r, dict) for r in rows):
        raise UpsilError("csv: rows are either all dicts or all lists", "csv: строки — либо все словари, либо все списки")
    if columns is not None:
        writer.writerow(columns)
    for r in rows:
        writer.writerow([_cell(v) for v in r])
    return out.getvalue()


def _cell(value: Any) -> Any:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return ""
    return value


def write(path: str, rows: List[Any], columns: Optional[List[str]] = None, sep: str = ",") -> int:
    """Write rows to a CSV file; returns how many rows were written."""
    rows = list(rows)
    _Path(path).expanduser().write_text(stringify(rows, columns, sep), encoding="utf-8")
    return len(rows)
