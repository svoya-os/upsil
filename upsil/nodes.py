# SPDX-License-Identifier: Apache-2.0
"""UpsiL syntax tree.

Every node carries a :class:`Span` (1-based line and column of its first
character, and the position just after its last character) so that compile
errors and the generated Python code can point back at the ``.upl`` source.

The checker (``upsil.checker``) annotates nodes in place: names get ``sym``
(the declaration they refer to), functions and classes get their scopes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union


@dataclass(frozen=True)
class Span:
    line: int
    col: int
    end_line: int
    end_col: int

    def to(self, other: "Span") -> "Span":
        """The span from the start of ``self`` to the end of ``other``."""
        return Span(self.line, self.col, other.end_line, other.end_col)

    @staticmethod
    def point(line: int, col: int) -> "Span":
        return Span(line, col, line, col + 1)


class Node:
    span: Span
    # set by the checker
    sym = None
    # set by the parser for an expression written in parentheses
    parens = False


# --------------------------------------------------------------------------
# types (recorded, only linted by `upsil check`)

@dataclass
class TypeRef(Node):
    span: Span
    name: str                      # dotted name: "int", "torch.Tensor"
    args: List["TypeRef"] = field(default_factory=list)
    nullable: bool = False


# --------------------------------------------------------------------------
# expressions

@dataclass
class Num(Node):
    span: Span
    value: Union[int, float]


@dataclass
class Interp(Node):
    """``{expr}`` or ``{expr:spec}`` inside a string literal."""
    span: Span
    expr: Node
    spec: Optional[str] = None


@dataclass
class Str(Node):
    span: Span
    parts: List[Union[str, Interp]]

    @property
    def is_plain(self) -> bool:
        return all(isinstance(p, str) for p in self.parts)

    @property
    def text(self) -> str:
        return "".join(p for p in self.parts if isinstance(p, str))


@dataclass
class Const(Node):
    """``true``, ``false`` or ``null``."""
    span: Span
    value: Optional[bool]


@dataclass
class Name(Node):
    span: Span
    name: str


@dataclass
class ListLit(Node):
    span: Span
    items: List[Node]


@dataclass
class DictLit(Node):
    span: Span
    items: List[Tuple[Node, Node]]


@dataclass
class Unary(Node):
    span: Span
    op: str                        # "-" or "+"
    operand: Node


@dataclass
class Not(Node):
    span: Span
    operand: Node


@dataclass
class BinOp(Node):
    span: Span
    op: str                        # + - * / % @ **
    left: Node
    right: Node


@dataclass
class BoolOp(Node):
    span: Span
    op: str                        # "and" | "or"
    left: Node
    right: Node


@dataclass
class Compare(Node):
    span: Span
    op: str                        # == != < <= > >= in "not in"
    left: Node
    right: Node


@dataclass
class Range(Node):
    span: Span
    start: Node
    end: Node
    inclusive: bool


@dataclass
class Arg(Node):
    span: Span
    name: Optional[str]
    value: Node


@dataclass
class Call(Node):
    span: Span
    func: Node
    args: List[Arg]


@dataclass
class Slice(Node):
    span: Span
    lo: Optional[Node]
    hi: Optional[Node]
    step: Optional[Node]


@dataclass
class Index(Node):
    span: Span
    obj: Node
    items: List[Node]              # expressions or Slice nodes


@dataclass
class Attr(Node):
    span: Span
    obj: Node
    name: str
    name_span: Span


@dataclass
class Prompt(Node):
    """``[model] => text`` / ``[model, system: s] => text -> json``."""
    span: Span
    model: Node
    text: Node
    system: Optional[Node] = None
    as_json: bool = False


# --------------------------------------------------------------------------
# statements

@dataclass
class VarDecl(Node):
    span: Span
    mutable: bool                  # var / val
    name: str
    name_span: Span
    type: Optional[TypeRef]
    value: Optional[Node]


@dataclass
class ResourceDecl(Node):
    """``llm m = ...`` or ``vector_store db = ...`` (value optional)."""
    span: Span
    kind: str                      # "llm" | "vector_store"
    name: str
    name_span: Span
    value: Optional[Node]


@dataclass
class Assign(Node):
    span: Span
    target: Node
    value: Node


@dataclass
class AugAssign(Node):
    span: Span
    target: Node
    op: str                        # "+", "-", "*", "/", "%"
    value: Node


@dataclass
class ExprStmt(Node):
    span: Span
    expr: Node


@dataclass
class If(Node):
    span: Span
    cond: Node
    body: List[Node]
    orelse: List[Node]             # [] | [If] (else if) | statements


@dataclass
class While(Node):
    span: Span
    cond: Node
    body: List[Node]


@dataclass
class For(Node):
    span: Span
    names: List[str]
    name_spans: List[Span]
    iter: Node
    body: List[Node]


@dataclass
class Break(Node):
    span: Span


@dataclass
class Continue(Node):
    span: Span


@dataclass
class Return(Node):
    span: Span
    value: Optional[Node]


@dataclass
class Param(Node):
    span: Span
    name: str
    type: Optional[TypeRef]
    default: Optional[Node]


@dataclass
class FunDecl(Node):
    span: Span
    name: str
    name_span: Span
    params: List[Param]
    ret: Optional[TypeRef]
    body: List[Node]
    kind: str = "fun"              # "fun" | "graph"
    # set by the checker
    scope = None
    is_method = False


@dataclass
class ClassDecl(Node):
    span: Span
    name: str
    name_span: Span
    fields: List[VarDecl]
    methods: List[FunDecl]
    is_model: bool = False
    # set by the checker
    init_scope = None


@dataclass
class Import(Node):
    """``import llm`` / ``import nn.functional as F``."""
    span: Span
    path: List[str]
    alias: Optional[str]


@dataclass
class PyImport(Node):
    """``import py "numpy" as np``."""
    span: Span
    module: str
    alias: Optional[str]


@dataclass
class Module(Node):
    span: Span
    body: List[Node]
