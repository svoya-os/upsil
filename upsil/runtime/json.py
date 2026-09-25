# SPDX-License-Identifier: Apache-2.0
r"""json: JSON text and files.

    import json
    val data = json.parse("\{\"a\": [1, 2]\}")   // braces in strings are written \{ \}
    print(json.stringify(data))                    // {"a": [1, 2]}
    json.write("out.json", data)
"""

from __future__ import annotations

import json as _json
from pathlib import Path as _Path
from typing import Any, Optional

__all__ = ["parse", "stringify", "read", "write"]


def parse(text: str) -> Any:
    """JSON text as UpsiL values; objects are records (``data.name`` or ``data["name"]``)."""
    from .prelude import records
    return records(_json.loads(text))


def stringify(value: Any, indent: Optional[int] = None) -> str:
    return _json.dumps(value, ensure_ascii=False, indent=indent)


def read(path: str) -> Any:
    return parse(_Path(path).expanduser().read_text(encoding="utf-8"))


def write(path: str, value: Any, indent: Optional[int] = 2) -> None:
    _Path(path).expanduser().write_text(stringify(value, indent) + "\n", encoding="utf-8")
