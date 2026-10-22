"""FastAPI wrapper over the TrellisDB library.

This is intentionally a thin layer:
- It does not implement database logic.
- It converts HTTP requests into calls to [`TrellisDB`](trellisdb/api.py:1).

Every handle is opened in a `with` block, so `TrellisDB.__exit__` releases it
(and any writer lock) as soon as the request is done.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, status

from trellisdb import TrellisDB
from trellisdb.errors import (
    LockError,
    ReadOnlyError,
    StorageCorruptionError,
    ValidationError,
)
from trellisdb.query.ast import Field
from trellisdb.server.schemas import DeleteBody, InitResponse, ItemBody

app = FastAPI(title="TrellisDB")


def _to_http(exc: Exception) -> HTTPException:
    if isinstance(exc, (ValidationError, ReadOnlyError)):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, KeyError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if isinstance(exc, LockError):
        return HTTPException(status_code=status.HTTP_423_LOCKED, detail=str(exc))
    if isinstance(exc, StorageCorruptionError):
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
    )


def _reject_non_standard_constant(name: str) -> Any:
    raise ValueError(f"not a standard JSON value: {name}")


def _decode_query_value(raw: str | None) -> Any:
    """Read a `/find` value as JSON when it parses; otherwise keep the string.

    `10` becomes an int, `true` a bool, `null` None and `"10"` the string
    `10`; a plain word such as `c1` stays a string. `NaN` and `Infinity` are
    not standard JSON, so they stay strings too.
    """

    if raw is None:
        return None
    try:
        return json.loads(raw, parse_constant=_reject_non_standard_constant)
    except ValueError:
        return raw


@app.get("/info")
def info(path: str) -> dict[str, Any]:
    try:
        with TrellisDB.open(path, mode="r") as db:
            return {"path": str(Path(path)), "dimensions": db.dimensions, "mode": "r"}
    except Exception as exc:  # noqa: BLE001
        raise _to_http(exc) from exc


@app.post("/init")
def init_db(path: str, dimensions: int, overwrite: bool = False) -> InitResponse:
    try:
        with TrellisDB.create(path, dimensions=dimensions, overwrite=overwrite) as db:
            return InitResponse(
                path=str(Path(path)),
                dimensions=db.dimensions,
                created=True,
            )
    except Exception as exc:  # noqa: BLE001
        raise _to_http(exc) from exc


@app.post("/item")
def set_item(path: str, body: ItemBody = Body(...)) -> dict[str, Any]:
    try:
        with TrellisDB.open(path, mode="rw") as db:
            db.set(tuple(body.coords), body.value)
            db.commit()
        return {"coords": body.coords, "value": body.value}
    except Exception as exc:  # noqa: BLE001
        raise _to_http(exc) from exc


@app.get("/item")
def get_item(path: str, coords: list[str] = Query(...)) -> dict[str, Any]:
    try:
        with TrellisDB.open(path, mode="r") as db:
            value = db.get(tuple(coords))
        return {"coords": coords, "value": value}
    except Exception as exc:  # noqa: BLE001
        raise _to_http(exc) from exc


@app.delete("/item")
def delete_item(path: str, body: DeleteBody = Body(...)) -> dict[str, Any]:
    try:
        with TrellisDB.open(path, mode="rw") as db:
            db.delete(tuple(body.coords))
            db.commit()
        return {"coords": body.coords, "deleted": True}
    except Exception as exc:  # noqa: BLE001
        raise _to_http(exc) from exc


@app.get("/list")
def list_items(
    path: str, prefix: list[str] | None = Query(None), depth: int | None = None
) -> dict[str, Any]:
    try:
        with TrellisDB.open(path, mode="r") as db:
            keys = db.list(prefix=tuple(prefix or ()), depth=depth)
        return {"keys": [list(k) for k in keys]}
    except Exception as exc:  # noqa: BLE001
        raise _to_http(exc) from exc


@app.get("/find")
def find_items(
    path: str,
    prefix: list[str] | None = Query(None),
    field: list[str] | None = Query(None),
    op: str = "==",
    value: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Minimal query endpoint.

    MVP: supports a single field predicate. `value` is decoded by
    `_decode_query_value`, so it can match a number, bool or null field.
    """

    try:
        with TrellisDB.open(path, mode="r") as db:
            expr = None
            if field is not None:
                literal = _decode_query_value(value)
                expr = Field(tuple(field), op, literal)  # type: ignore[arg-type]
            rows = db.find(prefix=tuple(prefix or ()), where=expr, limit=limit)
        return {"rows": [{"key": list(k), "value": v} for k, v in rows]}
    except Exception as exc:  # noqa: BLE001
        raise _to_http(exc) from exc
