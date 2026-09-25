# SPDX-License-Identifier: Apache-2.0
"""Stand-ins for torch and tkinter, so model blocks and ui can be tested
without PyTorch or a display. They mimic only what the tests touch."""

from __future__ import annotations

import contextlib
import sys
import types
from typing import Iterator


@contextlib.contextmanager
def modules(**replacements) -> Iterator[None]:
    """Temporarily replace entries of sys.modules (None makes an import fail)."""
    names = {name.replace("__", "."): mod for name, mod in replacements.items()}
    saved = {name: sys.modules.get(name, KeyError) for name in names}
    from upsil.runtime import nn as upsil_nn
    saved_torch = upsil_nn._torch
    upsil_nn._torch = None
    try:
        sys.modules.update(names)
        yield
    finally:
        for name, mod in saved.items():
            if mod is KeyError:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod
        upsil_nn._torch = saved_torch


def fake_torch() -> dict:
    torch = types.ModuleType("torch")
    nn = types.ModuleType("torch.nn")
    functional = types.ModuleType("torch.nn.functional")

    class Module:
        def __call__(self, *args, **kwargs):
            return self.forward(*args, **kwargs)

    class Linear(Module):
        def __init__(self, inputs, outputs):
            self.inputs, self.outputs = inputs, outputs

        def forward(self, x):
            return [sum(x)] * self.outputs

    def relu(x):
        return [max(0, v) for v in x]

    nn.Module = Module
    nn.Linear = Linear
    nn.functional = functional
    functional.relu = relu
    torch.nn = nn
    torch.tensor = lambda data: list(data)
    return {"torch": torch, "torch__nn": nn, "torch__nn__functional": functional}


class TclError(Exception):
    pass


def fake_tkinter(fail_display: bool = False) -> dict:
    tk = types.ModuleType("tkinter")
    scrolledtext = types.ModuleType("tkinter.scrolledtext")

    class Widget:
        def __init__(self, *args, **kwargs):
            self.options = dict(kwargs)
            self.text = ""
            self.value = ""
            self.bindings = {}

        def pack(self, **kwargs):
            pass

        def configure(self, **kwargs):
            self.options.update(kwargs)

        def insert(self, index, text):
            self.text += text

        def see(self, index):
            pass

        def get(self):
            return self.value

        def delete(self, first, last=None):
            self.value = ""

        def bind(self, event, handler):
            self.bindings[event] = handler

        def focus_set(self):
            pass

    class Tk(Widget):
        def __init__(self, *args, **kwargs):
            if fail_display:
                raise TclError("no display name and no $DISPLAY environment variable")
            super().__init__()
            self.after_calls = []
            self.destroyed = False

        def title(self, text):
            self.window_title = text

        def geometry(self, spec):
            self.window_geometry = spec

        def after(self, ms, func):
            self.after_calls.append(func)

        def protocol(self, name, func):
            pass

        def mainloop(self):
            pass

        def destroy(self):
            self.destroyed = True

    tk.Tk, tk.Frame, tk.Entry, tk.Button, tk.TclError = Tk, Widget, Widget, Widget, TclError
    scrolledtext.ScrolledText = Widget
    tk.scrolledtext = scrolledtext
    return {"tkinter": tk, "tkinter__scrolledtext": scrolledtext}
