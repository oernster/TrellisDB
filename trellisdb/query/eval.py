"""Query evaluation for TrellisDB."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from trellisdb.engine.keycodec import decode_key
from trellisdb.query.ast import And, Expr, Field, KeyDim, Not, Op, Or


def _contains(container: Any, item: Any) -> bool:
    if isinstance(container, str):
        return str(item) in container
    if isinstance(container, dict):
        return item in container
    if isinstance(container, Iterable):
        try:
            return item in container
        except TypeError:
            return False
    return False


def _apply_op(left: Any, op: Op, right: Any) -> bool:
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    if op == "in":
        return left in right
    if op == "contains":
        return _contains(left, right)
    raise ValueError(f"Unsupported operator: {op}")


def _get_field(value: Any, path: tuple[str, ...]) -> Any:
    cur = value
    for p in path:
        if not isinstance(cur, dict):
            return None
        if p not in cur:
            return None
        cur = cur[p]
    return cur


def evaluate(expr: Expr, *, encoded_key: str, value: Any) -> bool:
    if isinstance(expr, And):
        return evaluate(expr.left, encoded_key=encoded_key, value=value) and evaluate(
            expr.right, encoded_key=encoded_key, value=value
        )
    if isinstance(expr, Or):
        return evaluate(expr.left, encoded_key=encoded_key, value=value) or evaluate(
            expr.right, encoded_key=encoded_key, value=value
        )
    if isinstance(expr, Not):
        return not evaluate(expr.expr, encoded_key=encoded_key, value=value)
    if isinstance(expr, KeyDim):
        key_components = decode_key(encoded_key)
        left = key_components[expr.index]
        return _apply_op(left, expr.op, expr.value)
    if isinstance(expr, Field):
        left = _get_field(value, expr.path)
        return _apply_op(left, expr.op, expr.value)
    raise TypeError(f"Unsupported expression type: {type(expr)}")
