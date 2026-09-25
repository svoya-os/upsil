# SPDX-License-Identifier: Apache-2.0
"""A small, honest stand-in for PyTorch on numpy, so neural-network programs run in tests.

It implements reverse-mode autograd for the part of the torch API that UpsiL's examples and
``nn`` helpers use: tensors (arithmetic, matmul, reductions, indexing, comparisons),
``torch.nn`` (Module, Linear, ReLU, Tanh, Sigmoid, Dropout, Sequential, Embedding, LayerNorm),
losses (cross entropy, binary cross entropy, MSE), ``torch.optim`` (SGD with momentum, Adam),
``torch.utils.data`` (TensorDataset, DataLoader), ``no_grad``, ``save``/``load`` and the CPU
"device". Everything runs on float32 numpy arrays on the CPU. It is a test double, not a
product: the real thing is ``pip install torch``.

``install()`` puts it into ``sys.modules`` as ``torch`` (and its submodules) and returns an
undo function.
"""

from __future__ import annotations

import contextlib
import math
import pickle
import sys
import types
from typing import Any, Callable, Iterable, Iterator, List, Optional, Sequence, Tuple

import numpy as np

float32 = np.float32
float64 = np.float64
int64 = np.int64
long = np.int64
bool_ = np.bool_

_GRAD = [True]
_RNG = [np.random.default_rng(0)]


def is_grad_enabled() -> bool:
    return _GRAD[0]


class _GradMode:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.prev = True

    def __enter__(self):
        self.prev = _GRAD[0]
        _GRAD[0] = self.enabled
        return self

    def __exit__(self, *exc) -> None:
        _GRAD[0] = self.prev

    def __call__(self, fn: Callable) -> Callable:          # usable as a decorator too
        def wrapped(*args, **kwargs):
            with _GradMode(self.enabled):
                return fn(*args, **kwargs)
        return wrapped


def no_grad() -> _GradMode:
    return _GradMode(False)


def enable_grad() -> _GradMode:
    return _GradMode(True)


def set_grad_enabled(mode: bool) -> _GradMode:
    _GRAD[0] = bool(mode)
    return _GradMode(bool(mode))


def manual_seed(seed: int) -> None:
    _RNG[0] = np.random.default_rng(int(seed))


def _as_array(value: Any, dtype=None) -> np.ndarray:
    if isinstance(value, Tensor):
        value = value.data
    arr = np.asarray(value, dtype=dtype)
    if dtype is None:
        if arr.dtype.kind == "f":
            arr = arr.astype(np.float32)
        elif arr.dtype.kind in "iu":
            arr = arr.astype(np.int64)
    return arr


def _unbroadcast(grad: np.ndarray, shape: Tuple[int, ...]) -> np.ndarray:
    while grad.ndim > len(shape):
        grad = grad.sum(axis=0)
    for axis, size in enumerate(shape):
        if size == 1 and grad.shape[axis] != 1:
            grad = grad.sum(axis=axis, keepdims=True)
    return grad.reshape(shape)


class device:
    def __init__(self, kind: str = "cpu") -> None:
        self.type = str(kind).split(":")[0]

    def __repr__(self) -> str:
        return f"device(type='{self.type}')"

    def __eq__(self, other) -> bool:
        return str(other).split(":")[0] == self.type if isinstance(other, str) else getattr(other, "type", None) == self.type

    def __str__(self) -> str:
        return self.type


class Tensor:
    __array_priority__ = 100

    def __init__(self, data: Any, requires_grad: bool = False, _parents: Sequence["Tensor"] = (),
                 _fns: Sequence[Callable[[np.ndarray], np.ndarray]] = ()) -> None:
        self.data = _as_array(data)
        self.grad: Optional[Tensor] = None
        self.requires_grad = bool(requires_grad)
        self._parents = tuple(_parents)      # graph edges: parent tensors …
        self._fns = tuple(_fns)              # … and, for each, upstream gradient → parent gradient
        self.device = device("cpu")

    # -- basics -------------------------------------------------------------------------------
    @property
    def shape(self) -> Tuple[int, ...]:
        return tuple(self.data.shape)

    @property
    def dtype(self):
        return self.data.dtype.type

    @property
    def ndim(self) -> int:
        return self.data.ndim

    def size(self, dim: Optional[int] = None):
        return self.shape if dim is None else self.shape[dim]

    def dim(self) -> int:
        return self.data.ndim

    def numel(self) -> int:
        return int(self.data.size)

    def __len__(self) -> int:
        return self.shape[0]

    def item(self):
        return self.data.item()

    def tolist(self):
        return self.data.tolist()

    def numpy(self) -> np.ndarray:
        return self.data.copy()

    def detach(self) -> "Tensor":
        return Tensor(self.data.copy())

    def clone(self) -> "Tensor":
        return self._unary(self.data.copy(), lambda g: g)

    def to(self, *args, **kwargs) -> "Tensor":
        for a in list(args) + list(kwargs.values()):
            if isinstance(a, type) and issubclass(a, np.generic):
                return self._unary(self.data.astype(a), lambda g: g)
        return self

    def cpu(self) -> "Tensor":
        return self

    def cuda(self) -> "Tensor":
        raise RuntimeError("microtorch: no CUDA (CPU only)")

    def float(self) -> "Tensor":
        return self._unary(self.data.astype(np.float32), lambda g: g)

    def long(self) -> "Tensor":
        return Tensor(self.data.astype(np.int64))

    def int(self) -> "Tensor":
        return Tensor(self.data.astype(np.int64))

    def bool(self) -> "Tensor":
        return Tensor(self.data.astype(np.bool_))

    def requires_grad_(self, flag: bool = True) -> "Tensor":
        self.requires_grad = flag
        return self

    def zero_(self) -> "Tensor":
        self.data[...] = 0
        return self

    def __repr__(self) -> str:
        body = np.array2string(self.data, precision=4, separator=", ")
        return f"tensor({body})"

    def __iter__(self) -> Iterator["Tensor"]:
        for i in range(self.shape[0]):
            yield self[i]

    def __bool__(self) -> bool:
        return bool(self.data)

    def __float__(self) -> float:
        return float(self.data)

    def __int__(self) -> int:
        return int(self.data)

    def __index__(self) -> int:
        return int(self.data)

    def __hash__(self) -> int:
        return id(self)

    # -- graph plumbing ---------------------------------------------------------------------------
    def _needs(self, *others: "Tensor") -> bool:
        return _GRAD[0] and (self.requires_grad or any(o.requires_grad for o in others))

    def _unary(self, out: np.ndarray, grad_fn: Callable[[np.ndarray], np.ndarray]) -> "Tensor":
        if not self._needs():
            return Tensor(out)
        return Tensor(out, True, (self,), (grad_fn,))

    def backward(self, gradient: Optional["Tensor"] = None) -> None:
        if gradient is None:
            if self.data.size != 1:
                raise RuntimeError("grad can be implicitly created only for scalar outputs")
            seed = np.ones_like(self.data, dtype=np.float32)
        else:
            seed = _as_array(gradient, np.float32)
        order: List[Tensor] = []
        seen = set()
        stack = [(self, False)]
        while stack:                                   # iterative topological sort (deep graphs)
            node, done = stack.pop()
            if done:
                order.append(node)
                continue
            if id(node) in seen:
                continue
            seen.add(id(node))
            stack.append((node, True))
            for parent in node._parents:
                if id(parent) not in seen:
                    stack.append((parent, False))
        grads = {id(self): seed}
        for node in reversed(order):
            g = grads.pop(id(node), None)
            if g is None:
                continue
            if not node._parents:                       # a leaf: keep the gradient
                if node.requires_grad:
                    g = _unbroadcast(np.asarray(g, dtype=np.float32), node.shape)
                    node.grad = Tensor(g.copy()) if node.grad is None else Tensor(node.grad.data + g)
                continue
            for parent, fn in zip(node._parents, node._fns):
                if not parent.requires_grad:
                    continue
                pg = _unbroadcast(np.asarray(fn(g), dtype=np.float32), parent.shape)
                grads[id(parent)] = grads[id(parent)] + pg if id(parent) in grads else pg

    # -- arithmetic -------------------------------------------------------------------------------
    def _binary(self, other: Any, out: np.ndarray, ga: Callable, gb: Callable) -> "Tensor":
        other_t = other if isinstance(other, Tensor) else Tensor(other)
        if not self._needs(other_t):
            return Tensor(out)
        return Tensor(out, True, (self, other_t), (ga, gb))

    def __add__(self, other):
        o = _as_array(other)
        return self._binary(other, self.data + o, lambda g: g, lambda g: g)

    __radd__ = __add__

    def __sub__(self, other):
        o = _as_array(other)
        return self._binary(other, self.data - o, lambda g: g, lambda g: -g)

    def __rsub__(self, other):
        return Tensor(other) - self if not isinstance(other, Tensor) else other - self

    def __mul__(self, other):
        o = _as_array(other)
        return self._binary(other, self.data * o, lambda g: g * o, lambda g: g * self.data)

    __rmul__ = __mul__

    def __truediv__(self, other):
        o = _as_array(other)
        return self._binary(other, self.data / o, lambda g: g / o, lambda g: -g * self.data / (o * o))

    def __rtruediv__(self, other):
        return Tensor(other) / self

    def __neg__(self):
        return self._unary(-self.data, lambda g: -g)

    def __pow__(self, p):
        p = float(p)
        return self._unary(self.data ** p, lambda g: g * p * self.data ** (p - 1))

    def __matmul__(self, other):
        o = other if isinstance(other, Tensor) else Tensor(other)
        a, b = self.data, o.data

        def ga(g):
            return g @ np.swapaxes(b, -1, -2) if b.ndim > 1 else np.outer(g, b) if a.ndim > 1 else g * b

        def gb(g):
            return np.swapaxes(a, -1, -2) @ g if a.ndim > 1 else np.outer(a, g) if b.ndim > 1 else g * a
        return self._binary(o, a @ b, ga, gb)

    def __rmatmul__(self, other):
        return Tensor(other) @ self

    # comparisons (no gradient)
    def __eq__(self, other):  # type: ignore[override]
        return Tensor(self.data == _as_array(other))

    def __ne__(self, other):  # type: ignore[override]
        return Tensor(self.data != _as_array(other))

    def __lt__(self, other):
        return Tensor(self.data < _as_array(other))

    def __le__(self, other):
        return Tensor(self.data <= _as_array(other))

    def __gt__(self, other):
        return Tensor(self.data > _as_array(other))

    def __ge__(self, other):
        return Tensor(self.data >= _as_array(other))

    # -- indexing ---------------------------------------------------------------------------------
    def __getitem__(self, index):
        idx = _index(index)
        out = self.data[idx]

        def grad(g):
            full = np.zeros_like(self.data, dtype=np.float32)
            np.add.at(full, idx, g)
            return full
        return self._unary(np.array(out), grad)

    def __setitem__(self, index, value) -> None:
        self.data[_index(index)] = _as_array(value)

    # -- shape ------------------------------------------------------------------------------------
    def reshape(self, *shape):
        shape = shape[0] if len(shape) == 1 and isinstance(shape[0], (tuple, list)) else shape
        return self._unary(self.data.reshape(shape), lambda g: g.reshape(self.shape))

    view = reshape

    def flatten(self, start_dim: int = 0):
        lead = self.shape[:start_dim]
        return self.reshape(*lead, -1)

    def unsqueeze(self, dim: int):
        return self._unary(np.expand_dims(self.data, dim), lambda g: g.reshape(self.shape))

    def squeeze(self, dim: Optional[int] = None):
        out = np.squeeze(self.data) if dim is None else np.squeeze(self.data, axis=dim) if self.shape[dim] == 1 else self.data
        return self._unary(out, lambda g: g.reshape(self.shape))

    def t(self):
        return self._unary(self.data.T, lambda g: g.T)

    @property
    def T(self):
        return self.t()

    def transpose(self, a: int, b: int):
        return self._unary(np.swapaxes(self.data, a, b), lambda g: np.swapaxes(g, a, b))

    # -- reductions ---------------------------------------------------------------------------------
    def sum(self, dim: Optional[int] = None, keepdim: bool = False):
        out = self.data.sum(axis=dim, keepdims=keepdim)

        def grad(g):
            if dim is not None and not keepdim:
                g = np.expand_dims(g, dim)
            return np.broadcast_to(g, self.shape)
        return self._unary(np.asarray(out, dtype=np.float32) if self.data.dtype.kind == "f" else np.asarray(out), grad)

    def mean(self, dim: Optional[int] = None, keepdim: bool = False):
        n = self.data.size if dim is None else self.shape[dim]
        return self.float().sum(dim, keepdim) / n

    def max(self, dim: Optional[int] = None, keepdim: bool = False):
        if dim is None:
            return Tensor(self.data.max())
        values = self.data.max(axis=dim, keepdims=keepdim)
        indices = self.data.argmax(axis=dim)
        return types.SimpleNamespace(values=Tensor(values), indices=Tensor(indices))

    def argmax(self, dim: Optional[int] = None, keepdim: bool = False):
        out = self.data.argmax(axis=dim)
        if keepdim and dim is not None:
            out = np.expand_dims(out, dim)
        return Tensor(np.asarray(out, dtype=np.int64))

    def abs(self):
        return self._unary(np.abs(self.data), lambda g: g * np.sign(self.data))

    def exp(self):
        out = np.exp(self.data)
        return self._unary(out, lambda g: g * out)

    def log(self):
        return self._unary(np.log(self.data), lambda g: g / self.data)

    def sqrt(self):
        out = np.sqrt(self.data)
        return self._unary(out, lambda g: g / (2 * out))

    def relu(self):
        return self._unary(np.maximum(self.data, 0), lambda g: g * (self.data > 0))

    def tanh(self):
        out = np.tanh(self.data)
        return self._unary(out, lambda g: g * (1 - out * out))

    def sigmoid(self):
        out = 1 / (1 + np.exp(-self.data))
        return self._unary(out, lambda g: g * out * (1 - out))

    def softmax(self, dim: int = -1):
        return softmax(self, dim)

    def log_softmax(self, dim: int = -1):
        return log_softmax(self, dim)

    def clamp(self, min=None, max=None):  # noqa: A002 - torch's names
        out = np.clip(self.data, min, max)
        mask = np.ones_like(self.data, dtype=np.float32)
        if min is not None:
            mask = mask * (self.data >= min)
        if max is not None:
            mask = mask * (self.data <= max)
        return self._unary(out, lambda g: g * mask)


def _index(index):
    if isinstance(index, tuple):
        return tuple(_index(i) for i in index)
    if isinstance(index, Tensor):
        return index.data
    if isinstance(index, list):
        return np.asarray(index)
    return index


# -- factories --------------------------------------------------------------------------------------
def tensor(data: Any, dtype=None, requires_grad: bool = False, device: Any = None) -> Tensor:
    if isinstance(data, (list, tuple)) and data and isinstance(data[0], Tensor):
        data = [d.data for d in data]
    return Tensor(_as_array(data, dtype), requires_grad=requires_grad)


def as_tensor(data: Any, dtype=None) -> Tensor:
    return tensor(data, dtype)


def zeros(*shape, dtype=None, requires_grad: bool = False) -> Tensor:
    shape = shape[0] if len(shape) == 1 and isinstance(shape[0], (tuple, list)) else shape
    return Tensor(np.zeros(shape, dtype=dtype or np.float32), requires_grad)


def ones(*shape, dtype=None, requires_grad: bool = False) -> Tensor:
    shape = shape[0] if len(shape) == 1 and isinstance(shape[0], (tuple, list)) else shape
    return Tensor(np.ones(shape, dtype=dtype or np.float32), requires_grad)


def randn(*shape, requires_grad: bool = False) -> Tensor:
    shape = shape[0] if len(shape) == 1 and isinstance(shape[0], (tuple, list)) else shape
    return Tensor(_RNG[0].standard_normal(shape).astype(np.float32), requires_grad)


def rand(*shape, requires_grad: bool = False) -> Tensor:
    shape = shape[0] if len(shape) == 1 and isinstance(shape[0], (tuple, list)) else shape
    return Tensor(_RNG[0].random(shape).astype(np.float32), requires_grad)


def randint(low: int, high: int, size: Sequence[int]) -> Tensor:
    return Tensor(_RNG[0].integers(low, high, size=tuple(size)).astype(np.int64))


def randperm(n: int) -> Tensor:
    return Tensor(_RNG[0].permutation(int(n)).astype(np.int64))


def arange(*args, dtype=None) -> Tensor:
    return Tensor(np.arange(*args, dtype=dtype))


def cat(tensors: Sequence[Tensor], dim: int = 0) -> Tensor:
    return Tensor(np.concatenate([t.data for t in tensors], axis=dim))


def stack(tensors: Sequence[Tensor], dim: int = 0) -> Tensor:
    return Tensor(np.stack([t.data for t in tensors], axis=dim))


def argmax(t: Tensor, dim: Optional[int] = None) -> Tensor:
    return t.argmax(dim)


def softmax(x: Tensor, dim: int = -1) -> Tensor:
    shifted = x.data - x.data.max(axis=dim, keepdims=True)
    e = np.exp(shifted)
    out = e / e.sum(axis=dim, keepdims=True)
    return x._unary(out, lambda g: out * (g - (g * out).sum(axis=dim, keepdims=True)))


def log_softmax(x: Tensor, dim: int = -1) -> Tensor:
    shifted = x.data - x.data.max(axis=dim, keepdims=True)
    lse = np.log(np.exp(shifted).sum(axis=dim, keepdims=True))
    out = shifted - lse
    soft = np.exp(out)
    return x._unary(out, lambda g: g - soft * g.sum(axis=dim, keepdims=True))


def relu(x: Tensor) -> Tensor:
    return x.relu()


def tanh(x: Tensor) -> Tensor:
    return x.tanh()


def sigmoid(x: Tensor) -> Tensor:
    return x.sigmoid()


def exp(x: Tensor) -> Tensor:
    return x.exp()


def log(x: Tensor) -> Tensor:
    return x.log()


def mean(x: Tensor, dim: Optional[int] = None) -> Tensor:
    return x.mean(dim)


def sum(x: Tensor, dim: Optional[int] = None) -> Tensor:  # noqa: A001 - torch's name
    return x.sum(dim)


def is_tensor(x: Any) -> bool:
    return isinstance(x, Tensor)


def is_floating_point(x: Tensor) -> bool:
    return x.data.dtype.kind == "f"


# -- losses ---------------------------------------------------------------------------------------------
def cross_entropy(logits: Tensor, target: Tensor, reduction: str = "mean") -> Tensor:
    logp = log_softmax(logits, dim=-1)
    idx = np.arange(logits.shape[0])
    picked = logp[Tensor(idx), target]
    loss = -picked
    return loss.mean() if reduction == "mean" else loss.sum() if reduction == "sum" else loss


def nll_loss(logp: Tensor, target: Tensor) -> Tensor:
    idx = np.arange(logp.shape[0])
    return -(logp[Tensor(idx), target]).mean()


def binary_cross_entropy(p: Tensor, target: Tensor) -> Tensor:
    eps = 1e-7
    p = p.clamp(eps, 1 - eps)
    t = target if isinstance(target, Tensor) else Tensor(target)
    return -(t * p.log() + (1 - t) * (1 - p).log()).mean()


def binary_cross_entropy_with_logits(logits: Tensor, target: Tensor) -> Tensor:
    return binary_cross_entropy(logits.sigmoid(), target)


def mse_loss(a: Tensor, b: Tensor) -> Tensor:
    return ((a - b) ** 2).mean()


def l1_loss(a: Tensor, b: Tensor) -> Tensor:
    return (a - b).abs().mean()


# -- nn -------------------------------------------------------------------------------------------------
class Parameter(Tensor):
    def __init__(self, data: Any, requires_grad: bool = True) -> None:
        super().__init__(data, requires_grad=requires_grad)


class Module:
    def __init__(self) -> None:
        object.__setattr__(self, "_modules", {})
        object.__setattr__(self, "_params", {})
        object.__setattr__(self, "training", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if "_modules" not in self.__dict__:
            raise AttributeError("cannot assign before Module.__init__() call")
        if isinstance(value, Parameter):
            self._params[name] = value
        elif isinstance(value, Module):
            self._modules[name] = value
        object.__setattr__(self, name, value)

    def __call__(self, *args, **kwargs):
        return self.forward(*args, **kwargs)

    def forward(self, *args, **kwargs):
        raise NotImplementedError("forward")

    def named_parameters(self, prefix: str = "") -> Iterator[Tuple[str, Parameter]]:
        for name, p in self._params.items():
            yield prefix + name, p
        for name, m in self._modules.items():
            yield from m.named_parameters(prefix + name + ".")

    def parameters(self) -> Iterator[Parameter]:
        for _name, p in self.named_parameters():
            yield p

    def children(self) -> Iterator["Module"]:
        return iter(self._modules.values())

    def modules(self) -> Iterator["Module"]:
        yield self
        for m in self._modules.values():
            yield from m.modules()

    def train(self, mode: bool = True) -> "Module":
        for m in self.modules():
            object.__setattr__(m, "training", mode)
        return self

    def eval(self) -> "Module":
        return self.train(False)

    def to(self, *args, **kwargs) -> "Module":
        return self

    def cpu(self) -> "Module":
        return self

    def zero_grad(self) -> None:
        for p in self.parameters():
            p.grad = None

    def state_dict(self) -> dict:
        return {name: Tensor(p.data.copy()) for name, p in self.named_parameters()}

    def load_state_dict(self, state: dict, strict: bool = True):
        params = dict(self.named_parameters())
        missing = [k for k in params if k not in state]
        unexpected = [k for k in state if k not in params]
        if strict and (missing or unexpected):
            raise RuntimeError(f"Error(s) in loading state_dict: missing {missing}, unexpected {unexpected}")
        for name, value in state.items():
            if name in params:
                params[name].data = _as_array(value).astype(np.float32)
        return types.SimpleNamespace(missing_keys=missing, unexpected_keys=unexpected)

    def __repr__(self) -> str:
        inner = ", ".join(f"{k}={v!r}" for k, v in self._modules.items())
        return f"{type(self).__name__}({inner})"


class Linear(Module):
    def __init__(self, in_features: int, out_features: int, bias: bool = True) -> None:
        super().__init__()
        bound = 1 / math.sqrt(in_features)
        self.in_features, self.out_features = in_features, out_features
        self.weight = Parameter(_RNG[0].uniform(-bound, bound, (out_features, in_features)).astype(np.float32))
        if bias:
            self.bias = Parameter(_RNG[0].uniform(-bound, bound, (out_features,)).astype(np.float32))
        else:
            object.__setattr__(self, "bias", None)

    def forward(self, x: Tensor) -> Tensor:
        out = x @ self.weight.t()
        return out + self.bias if self.bias is not None else out

    def __repr__(self) -> str:
        return f"Linear(in_features={self.in_features}, out_features={self.out_features})"


class Embedding(Module):
    def __init__(self, num: int, dim: int) -> None:
        super().__init__()
        self.weight = Parameter(_RNG[0].standard_normal((num, dim)).astype(np.float32))

    def forward(self, idx: Tensor) -> Tensor:
        return self.weight[idx]


class LayerNorm(Module):
    def __init__(self, dim: int, eps: float = 1e-5) -> None:
        super().__init__()
        self.eps = eps
        self.weight = Parameter(np.ones(dim, dtype=np.float32))
        self.bias = Parameter(np.zeros(dim, dtype=np.float32))

    def forward(self, x: Tensor) -> Tensor:
        mu = x.mean(-1, keepdim=True)
        var = ((x - mu) ** 2).mean(-1, keepdim=True)
        return (x - mu) / (var + self.eps).sqrt() * self.weight + self.bias


class _Activation(Module):
    fn: Callable[[Tensor], Tensor]

    def forward(self, x: Tensor) -> Tensor:
        return type(self).fn(x)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class ReLU(_Activation):
    fn = staticmethod(relu)


class Tanh(_Activation):
    fn = staticmethod(tanh)


class Sigmoid(_Activation):
    fn = staticmethod(sigmoid)


class Softmax(Module):
    def __init__(self, dim: int = -1) -> None:
        super().__init__()
        self.dim = dim

    def forward(self, x: Tensor) -> Tensor:
        return softmax(x, self.dim)


class Dropout(Module):
    def __init__(self, p: float = 0.5) -> None:
        super().__init__()
        self.p = p

    def forward(self, x: Tensor) -> Tensor:
        if not self.training or self.p == 0:
            return x
        mask = (_RNG[0].random(x.shape) >= self.p).astype(np.float32) / (1 - self.p)
        return x * mask


class Flatten(Module):
    def forward(self, x: Tensor) -> Tensor:
        return x.flatten(1)


class Sequential(Module):
    def __init__(self, *layers: Module) -> None:
        super().__init__()
        for i, layer in enumerate(layers):
            setattr(self, str(i), layer)

    def forward(self, x: Tensor) -> Tensor:
        for layer in self._modules.values():
            x = layer(x)
        return x

    def __getitem__(self, i: int) -> Module:
        return list(self._modules.values())[i]

    def __len__(self) -> int:
        return len(self._modules)


class MSELoss(Module):
    def forward(self, a, b):
        return mse_loss(a, b)


class CrossEntropyLoss(Module):
    def forward(self, a, b):
        return cross_entropy(a, b)


class BCELoss(Module):
    def forward(self, a, b):
        return binary_cross_entropy(a, b)


# -- optim ----------------------------------------------------------------------------------------------
class Optimizer:
    def __init__(self, params: Iterable[Parameter], lr: float) -> None:
        self.params = [p for p in params]
        self.lr = lr
        self.param_groups = [{"lr": lr, "params": self.params}]

    def zero_grad(self, set_to_none: bool = True) -> None:
        for p in self.params:
            p.grad = None

    def _lr(self) -> float:
        return float(self.param_groups[0]["lr"])


class SGD(Optimizer):
    def __init__(self, params, lr: float = 0.01, momentum: float = 0.0, weight_decay: float = 0.0) -> None:
        super().__init__(params, lr)
        self.momentum, self.weight_decay = momentum, weight_decay
        self.buf = [np.zeros_like(p.data) for p in self.params]

    def step(self) -> None:
        for p, b in zip(self.params, self.buf):
            if p.grad is None:
                continue
            g = p.grad.data + self.weight_decay * p.data
            if self.momentum:
                b *= self.momentum
                b += g
                g = b
            p.data = p.data - self._lr() * g


class Adam(Optimizer):
    def __init__(self, params, lr: float = 1e-3, betas=(0.9, 0.999), eps: float = 1e-8, weight_decay: float = 0.0) -> None:
        super().__init__(params, lr)
        self.b1, self.b2 = betas
        self.eps, self.weight_decay = eps, weight_decay
        self.m = [np.zeros_like(p.data) for p in self.params]
        self.v = [np.zeros_like(p.data) for p in self.params]
        self.t = 0

    def step(self) -> None:
        self.t += 1
        for i, p in enumerate(self.params):
            if p.grad is None:
                continue
            g = p.grad.data + self.weight_decay * p.data
            self.m[i] = self.b1 * self.m[i] + (1 - self.b1) * g
            self.v[i] = self.b2 * self.v[i] + (1 - self.b2) * g * g
            mh = self.m[i] / (1 - self.b1 ** self.t)
            vh = self.v[i] / (1 - self.b2 ** self.t)
            p.data = p.data - self._lr() * mh / (np.sqrt(vh) + self.eps)


AdamW = Adam


# -- data -------------------------------------------------------------------------------------------------
class TensorDataset:
    def __init__(self, *tensors: Tensor) -> None:
        self.tensors = tensors

    def __len__(self) -> int:
        return len(self.tensors[0])

    def __getitem__(self, i):
        return tuple(t[i] for t in self.tensors)


class DataLoader:
    def __init__(self, dataset, batch_size: int = 1, shuffle: bool = False, drop_last: bool = False) -> None:
        self.dataset, self.batch_size, self.shuffle, self.drop_last = dataset, batch_size, shuffle, drop_last

    def __len__(self) -> int:
        n = len(self.dataset)
        return n // self.batch_size if self.drop_last else -(-n // self.batch_size)

    def __iter__(self):
        n = len(self.dataset)
        order = _RNG[0].permutation(n) if self.shuffle else np.arange(n)
        for start in range(0, n, self.batch_size):
            idx = order[start:start + self.batch_size]
            if self.drop_last and len(idx) < self.batch_size:
                break
            if isinstance(self.dataset, TensorDataset):
                yield tuple(Tensor(t.data[idx]) for t in self.dataset.tensors)
            else:
                items = [self.dataset[int(i)] for i in idx]
                if isinstance(items[0], tuple):
                    yield tuple(stack([it[k] if isinstance(it[k], Tensor) else Tensor(it[k]) for it in items]) for k in range(len(items[0])))
                else:
                    yield stack([it if isinstance(it, Tensor) else Tensor(it) for it in items])


# -- io ---------------------------------------------------------------------------------------------------
def save(obj: Any, path: str) -> None:
    with open(path, "wb") as f:
        pickle.dump(obj, f)


def load(path: str, map_location: Any = None, weights_only: bool = True) -> Any:
    with open(path, "rb") as f:
        return pickle.load(f)


# -- the module tree --------------------------------------------------------------------------------------
def install() -> Callable[[], None]:
    """Register this module as ``torch`` (+ torch.nn, torch.nn.functional, torch.optim,
    torch.utils.data, torch.cuda, torch.backends.mps); returns the undo function."""
    me = sys.modules[__name__]
    torch = types.ModuleType("torch")
    for name in dir(me):
        if not name.startswith("_") and name not in ("install", "np", "sys", "types", "pickle", "math", "contextlib"):
            setattr(torch, name, getattr(me, name))
    torch.__version__ = "0.0-microtorch"
    torch.bool = np.bool_
    nn = types.ModuleType("torch.nn")
    functional = types.ModuleType("torch.nn.functional")
    for name in ("Module", "Linear", "Embedding", "LayerNorm", "ReLU", "Tanh", "Sigmoid", "Softmax", "Dropout",
                 "Flatten", "Sequential", "Parameter", "MSELoss", "CrossEntropyLoss", "BCELoss"):
        setattr(nn, name, getattr(me, name))
    for name in ("relu", "tanh", "sigmoid", "softmax", "log_softmax", "cross_entropy", "nll_loss",
                 "binary_cross_entropy", "binary_cross_entropy_with_logits", "mse_loss", "l1_loss"):
        setattr(functional, name, getattr(me, name))
    nn.functional = functional
    optim = types.ModuleType("torch.optim")
    optim.SGD, optim.Adam, optim.AdamW, optim.Optimizer = SGD, Adam, AdamW, Optimizer
    utils = types.ModuleType("torch.utils")
    data = types.ModuleType("torch.utils.data")
    data.TensorDataset, data.DataLoader = TensorDataset, DataLoader
    utils.data = data
    cuda = types.ModuleType("torch.cuda")
    cuda.is_available = lambda: False
    cuda.device_count = lambda: 0
    backends = types.ModuleType("torch.backends")
    mps = types.ModuleType("torch.backends.mps")
    mps.is_available = lambda: False
    backends.mps = mps
    torch.nn, torch.optim, torch.utils, torch.cuda, torch.backends = nn, optim, utils, cuda, backends
    mods = {"torch": torch, "torch.nn": nn, "torch.nn.functional": functional, "torch.optim": optim,
            "torch.utils": utils, "torch.utils.data": data, "torch.cuda": cuda, "torch.backends": backends,
            "torch.backends.mps": mps}
    saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)

    def undo() -> None:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    return undo
