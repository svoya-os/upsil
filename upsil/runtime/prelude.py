# SPDX-License-Identifier: Apache-2.0
"""Helpers used by compiled UpsiL programs.

Generated code imports this module as ``_upsil``; the builtins that UpsiL
implements itself (``print``, ``input``, ``str``, ``div``, ``error``) are
imported by name. Values are shown the UpsiL way: ``true``, ``false``,
``null``, ``[1, "a"]``, ``{"k": 1}``.
"""

from __future__ import annotations

import builtins as _builtins
import importlib as _importlib
import json as _json
import sys as _sys

from ..errors import UpsilError

range = _builtins.range
format = _builtins.format


class _Missing:
    """Marks a parameter whose default must be computed at call time."""
    __slots__ = ()

    def __repr__(self) -> _builtins.str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING = _Missing()


# ---------------------------------------------------------------------- display

def show(value: object) -> _builtins.str:
    """The text of a value as UpsiL shows it (used by print, str and "{...}")."""
    return _show(value, False, set())


def _show(x: object, nested: bool, seen: set) -> _builtins.str:
    if x is None:
        return "null"
    if x is True:
        return "true"
    if x is False:
        return "false"
    if isinstance(x, _builtins.str):
        return _json.dumps(x, ensure_ascii=False) if nested else _builtins.str.__str__(x)
    if isinstance(x, bool):          # numpy/torch bools are not `bool`, but play safe
        return "true" if x else "false"
    if isinstance(x, int):
        return int.__repr__(x)
    if isinstance(x, float):
        return float.__repr__(x)
    if isinstance(x, (list, tuple, dict, set, frozenset)):
        if id(x) in seen:
            return "[...]" if isinstance(x, list) else "{...}"
        seen.add(id(x))
        try:
            if isinstance(x, list):
                return "[" + ", ".join(_show(v, True, seen) for v in x) + "]"
            if isinstance(x, tuple):
                inner = ", ".join(_show(v, True, seen) for v in x)
                return "(" + inner + ("," if len(x) == 1 else "") + ")"
            if isinstance(x, dict):
                return "{" + ", ".join(f"{_show(k, True, seen)}: {_show(v, True, seen)}"
                                       for k, v in x.items()) + "}"
            if not x:
                return "set()"
            return "{" + ", ".join(_show(v, True, seen) for v in x) + "}"
        finally:
            seen.discard(id(x))
    if isinstance(x, _builtins.range) and x.step == 1:
        return f"{x.start}..{x.stop}"
    return _builtins.str(x)


def type_name(value: object) -> _builtins.str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, _builtins.str):
        return "str"
    return type(value).__name__


class Object:
    """Base class of UpsiL classes: shows instances as ``Point(x=1, y=2)``."""

    def __repr__(self) -> _builtins.str:
        fields = ", ".join(f"{k}={_show(v, True, set())}" for k, v in self.__dict__.items()
                           if not k.startswith("_"))
        return f"{type(self).__name__}({fields})"

    __str__ = __repr__


# ---------------------------------------------------------------------- builtins

def print(*values: object, sep: _builtins.str = " ", end: _builtins.str = "\n") -> None:
    """Print values the UpsiL way; flushes when ``end`` has no line break."""
    _builtins.print(*[show(v) for v in values], sep=sep, end=end, flush="\n" not in end)


class _StrMeta(type):
    def __call__(cls, value: object = "", *args: object, **kwargs: object) -> _builtins.str:
        if args or kwargs:
            return _builtins.str(value, *args, **kwargs)
        return show(value)

    def __instancecheck__(cls, obj: object) -> bool:
        return isinstance(obj, _builtins.str)

    def __subclasscheck__(cls, sub: type) -> bool:
        return issubclass(sub, _builtins.str)

    def __getattr__(cls, name: _builtins.str) -> object:
        return getattr(_builtins.str, name)

    def __repr__(cls) -> _builtins.str:
        return "<class 'str'>"


class str(metaclass=_StrMeta):
    """``str(x)``: the text of ``x`` as UpsiL shows it; ``isinstance(s, str)`` works as usual."""


def input(prompt: object = "") -> object:
    """Read a line from the terminal; ``null`` at the end of input (Ctrl-D)."""
    try:
        return _builtins.input(show(prompt) if prompt != "" else "")
    except EOFError:
        return None


def div(a: object, b: object) -> object:
    """Integer (floor) division: ``div(7, 2) == 3``. ``//`` starts a comment in UpsiL."""
    return a // b  # type: ignore[operator]


def error(message: object) -> None:
    """Stop the program with an error message."""
    raise UpsilError(show(message))


def py_import(module: _builtins.str) -> object:
    _importlib.import_module(module)
    return _importlib.import_module(module.split(".")[0])


def repl_show(value: object) -> None:
    if value is not None:
        _builtins.print(_show(value, True, set()))


# ---------------------------------------------------------------------- AI

def prompt(model: object, text: object, *, system: object = None, json: bool = False) -> object:
    """``[model] => text`` and ``[model, system: s] => text -> json``."""
    ask = getattr(model, "ask", None)
    if ask is None or not callable(ask):
        name = type_name(model)
        raise UpsilError(f"[m] => ...: m must be an llm model (llm.Model(...)), not {name}",
                         f"[m] => ...: m должна быть моделью (llm.Model(...)), а не {name}")
    return ask(show(text), system=None if system is None else show(system), json=json)


def llm_resource(name: _builtins.str, value: object = MISSING) -> object:
    """``llm m`` / ``llm m = expr``: a default model, or a checked value."""
    if value is MISSING:
        from . import llm as _llm
        return _llm.Model()
    if not callable(getattr(value, "ask", None)):
        kind = type_name(value)
        raise UpsilError(f"llm {name}: expected an llm model (llm.Model(...)), got {kind}",
                         f"llm {name}: ожидалась модель (llm.Model(...)), а получено значение типа {kind}")
    return value


def store_resource(name: _builtins.str, value: object = MISSING) -> object:
    """``vector_store db`` / ``vector_store db = expr``."""
    if value is MISSING:
        from . import rag as _rag
        return _rag.VectorStore()
    if not (callable(getattr(value, "add", None)) and callable(getattr(value, "search", None))):
        kind = type_name(value)
        raise UpsilError(f"vector_store {name}: expected rag.VectorStore(...), got {kind}",
                         f"vector_store {name}: ожидалось rag.VectorStore(...), а получено значение типа {kind}")
    return value

