# SPDX-License-Identifier: Apache-2.0
"""Russian or English messages.

The language is read from the environment on every call, so a program (or a
test) can switch it at run time:

    UPSIL_LANG   ru | en           -- explicit choice, wins over everything
    LC_ALL, LC_MESSAGES, LANG      -- the usual POSIX order
    LANGUAGE                       -- first entry of the list

Anything that starts with "ru" means Russian; everything else means English.
Strings live next to the code as ``tr("English", "Русский")`` pairs so both
languages are always reviewed together.
"""

from __future__ import annotations

import os
from typing import Mapping, Optional


def detect_lang(env: Optional[Mapping[str, str]] = None) -> str:
    env = os.environ if env is None else env
    forced = env.get("UPSIL_LANG")
    if forced:
        return "ru" if forced.lower().startswith("ru") else "en"
    for key in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = env.get(key)
        if value:
            return "ru" if value.lower().startswith("ru") else "en"
    language = env.get("LANGUAGE", "")
    if language:
        return "ru" if language.split(":")[0].lower().startswith("ru") else "en"
    return "en"


def lang() -> str:
    return detect_lang()


def tr(en: str, ru: str) -> str:
    """Pick the string for the current language."""
    return ru if lang() == "ru" else en


def plural_ru(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def count_args(n: int) -> tuple:
    """``(en, ru)`` phrases for "N argument(s)"."""
    en = f"{n} argument" + ("" if n == 1 else "s")
    ru = f"{n} " + plural_ru(n, "аргумент", "аргумента", "аргументов")
    return en, ru
