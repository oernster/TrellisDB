"""Field/value indexes.

MVP approach: rebuild indexes on each commit for correctness and simplicity.
"""

from __future__ import annotations

import json
from typing import Any

from trellisdb.engine.storage import FieldIndexDef


def canonical_value_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _extract_field(value: Any, path: list[str]) -> Any:
    cur = value
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def rebuild_field_indexes(
    data: dict[str, Any], index_defs: list[FieldIndexDef]
) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for d in index_defs:
        out[d["name"]] = {}

    for encoded_key, doc in data.items():
        for d in index_defs:
            extracted = _extract_field(doc, d["path"])
            if extracted is None:
                continue
            vkey = canonical_value_key(extracted)
            bucket = out[d["name"]].setdefault(vkey, [])
            bucket.append(encoded_key)

    # Stable ordering for test determinism.
    for idx in out.values():
        for bucket in idx.values():
            bucket.sort()
    return out
