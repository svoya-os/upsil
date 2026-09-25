# SPDX-License-Identifier: Apache-2.0
"""nn: PyTorch for UpsiL, imported only when it is first used.

    import nn
    model Net {
        val l1 = nn.Linear(4, 8)
        val l2 = nn.Linear(8, 2)
        graph forward(x) { return l2(nn.relu(l1(x))) }
    }

``nn.X`` is looked up in ``torch.nn``, then ``torch.nn.functional``, then
``torch``: ``nn.Linear``, ``nn.relu``, ``nn.tensor``, ``nn.randn``,
``nn.optim.Adam``, ``nn.no_grad()``... ``nn.torch`` is the torch module
itself. ``model`` blocks become ``torch.nn.Module`` subclasses. Install
PyTorch separately (``pip install torch`` or ``uv tool install 'upsil[nn]'``).
"""

from __future__ import annotations

from typing import Any

from ..errors import UpsilError

_torch: Any = None


def _load() -> Any:
    global _torch
    if _torch is None:
        try:
            import torch
        except ImportError:
            raise UpsilError(
                "PyTorch is not installed, and `nn` and `model` blocks need it. "
                "Install it: pip install torch (or: uv tool install 'upsil[nn]')",
                "PyTorch не установлен, а он нужен модулю nn и блокам model. "
                "Установите: pip install torch (или: uv tool install 'upsil[nn]')") from None
        _torch = torch
    return _torch


def available() -> bool:
    """True if PyTorch can be imported."""
    try:
        _load()
    except UpsilError:
        return False
    return True


def __getattr__(name: str) -> Any:
    if name.startswith("__"):
        raise AttributeError(name)
    torch = _load()
    if name == "torch":
        return torch
    for namespace in (torch.nn, torch.nn.functional, torch):
        if hasattr(namespace, name):
            return getattr(namespace, name)
    raise AttributeError(f"nn has no '{name}' (looked in torch.nn, torch.nn.functional and torch)")
