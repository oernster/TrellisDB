"""Query expression tree (AST)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Op = Literal["==", "!=", "<", "<=", ">", ">=", "in", "contains"]


@dataclass(frozen=True)
class Expr:
    pass


@dataclass(frozen=True)
class And(Expr):
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Or(Expr):
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Not(Expr):
    expr: Expr


@dataclass(frozen=True)
class KeyDim(Expr):
    index: int
    op: Op
    value: Any


@dataclass(frozen=True)
class Field(Expr):
    path: tuple[str, ...]
    op: Op
    value: Any


def is_simple_field_equality(expr: Expr) -> bool:
    return isinstance(expr, Field) and expr.op == "=="
