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
itself. UpsiL adds ``nn.fit``, ``nn.batches``, ``nn.evaluating``,
``nn.accuracy``, ``nn.auto_device`` and ``nn.count_params``. ``model`` blocks become ``torch.nn.Module`` subclasses. Install
PyTorch separately (``pip install torch`` or ``uv tool install 'upsil[nn]'``).
"""

from __future__ import annotations

import contextlib as _contextlib
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


# ---------------------------------------------------------------------- helpers
# UpsiL's own names; everything else comes from torch (see __getattr__ below).

def auto_device() -> str:
    """The best device here: "cuda" (NVIDIA or ROCm), "mps" (Apple) or "cpu"."""
    torch = _load()
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(getattr(torch, "backends", None), "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def count_params(model: Any, trainable: bool = True) -> int:
    """How many numbers the model learns (only trainable ones unless trainable = false)."""
    return int(sum(p.numel() for p in model.parameters() if p.requires_grad or not trainable))


def batches(*tensors: Any, size: int = 32, shuffle: bool = False, drop_last: bool = False):
    """Mini-batches of equally long tensors: ``for ((xb, yb) in nn.batches(x, y, size = 32, shuffle = true))``.
    With one tensor each batch is that tensor's slice."""
    torch = _load()
    if not tensors:
        raise UpsilError("nn.batches needs at least one tensor", "nn.batches нужен хотя бы один тензор")
    n = len(tensors[0])
    for t in tensors[1:]:
        if len(t) != n:
            raise UpsilError(f"nn.batches: the tensors differ in length ({n} and {len(t)})",
                             f"nn.batches: у тензоров разная длина ({n} и {len(t)})")
    size = int(size)
    if size < 1:
        raise UpsilError("nn.batches: size must be at least 1", "nn.batches: size должен быть не меньше 1")
    order = torch.randperm(n) if shuffle else torch.arange(n)
    for start in range(0, n, size):
        part = order[start:start + size]
        if drop_last and len(part) < size:
            break
        out = tuple(t[part] for t in tensors)
        yield out[0] if len(out) == 1 else out


@_contextlib.contextmanager
def evaluating(model: Any):
    """``with nn.evaluating(net) { ... }``: evaluation mode and no gradients inside, the old state after."""
    torch = _load()
    was_training = bool(getattr(model, "training", True))
    model.eval()
    try:
        with torch.no_grad():
            yield model
    finally:
        model.train(was_training)


def _predict_labels(out: Any) -> Any:
    if out.dim() == 1 or out.shape[-1] == 1:           # one output: a probability of class 1
        return (out.reshape(-1) > 0.5).long()
    return out.argmax(dim=-1)


def _device_of(model: Any) -> Any:
    for p in model.parameters():
        return p.device
    return "cpu"


def accuracy(model: Any, x: Any, y: Any, batch: int = 1024) -> float:
    """Share of correct answers of a classifier (argmax, or > 0.5 for one output); 0.0–1.0."""
    device = _device_of(model)
    right = 0
    total = 0
    with evaluating(model):
        for xb, yb in batches(x, y, size=batch):
            pred = _predict_labels(model(xb.to(device)))
            right += int((pred == yb.to(device).reshape(-1).long()).sum().item())
            total += len(yb)
    return right / total if total else 0.0


def _default_loss(torch: Any, y: Any) -> Any:
    if not torch.is_floating_point(y):
        return torch.nn.functional.cross_entropy
    return torch.nn.functional.mse_loss


def fit(model: Any, x: Any, y: Any, *, epochs: int = 10, lr: float = 1e-3, batch: int = 32,
        loss: Any = None, optimizer: Any = None, val: Any = None, every: int = 1,
        device: Any = None, shuffle: bool = True, quiet: bool = False) -> list:
    """Train ``model`` on ``x`` → ``y`` and return the history (one record per epoch).

    Defaults: Adam with ``lr``; cross entropy when ``y`` holds class numbers, MSE when it holds
    floats (pass ``loss = nn.binary_cross_entropy`` for 0/1 probabilities). ``val = (x_val, y_val)``
    adds a validation loss (and accuracy for classes) to the report printed every ``every`` epochs.
    Ctrl+C stops the training early and still returns what was learned."""
    from .prelude import print as upsil_print
    from ..i18n import tr
    torch = _load()
    device = device or auto_device()
    model.to(device)
    loss_fn = loss or _default_loss(torch, y)
    classes = not torch.is_floating_point(y)
    opt = optimizer or torch.optim.Adam(model.parameters(), lr=lr)
    history: list = []
    epochs = int(epochs)
    width = len(str(epochs))
    try:
        for epoch in range(1, epochs + 1):
            model.train()
            total = 0.0
            count = 0
            for xb, yb in batches(x, y, size=batch, shuffle=shuffle):
                xb, yb = xb.to(device), yb.to(device)
                opt.zero_grad()
                value = loss_fn(model(xb), yb)
                value.backward()
                opt.step()
                total += float(value.item()) * len(xb)
                count += len(xb)
            record = {"epoch": epoch, "loss": total / max(count, 1)}
            if val is not None:
                vx, vy = val
                with evaluating(model):
                    out = model(vx.to(device))
                    record["val_loss"] = float(loss_fn(out, vy.to(device)).item())
                if classes:
                    record["val_accuracy"] = accuracy(model, vx, vy)
            history.append(record)
            if not quiet and (epoch % max(1, int(every)) == 0 or epoch == epochs):
                line = tr(f"epoch {epoch:{width}}/{epochs}", f"эпоха {epoch:{width}}/{epochs}")
                line += f" · loss {record['loss']:.4f}"
                if "val_loss" in record:
                    line += f" · val {record['val_loss']:.4f}"
                if "val_accuracy" in record:
                    line += tr(f" · accuracy {record['val_accuracy']:.1%}", f" · точность {record['val_accuracy']:.1%}")
                upsil_print(line)
    except KeyboardInterrupt:
        upsil_print(tr(f"stopped after {len(history)} epoch(s)", f"остановлено после эпох: {len(history)}"))
    model.eval()
    return history


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
