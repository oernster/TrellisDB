from __future__ import annotations

from pathlib import Path

from trellisdb import TrellisDB
from trellisdb.query.ast import Field


def test_find_uses_field_index_for_simple_equality_with_prefix(tmp_path: Path) -> None:
    db_path = tmp_path / "db.json"
    db = TrellisDB.create(db_path, dimensions=2)

    # Configure a field index on customer_id.
    db.define_field_index("by_customer_id", ("customer_id",))

    db.set(("orders", "1"), {"customer_id": "c1", "amount": 10})
    db.set(("orders", "2"), {"customer_id": "c2", "amount": 20})
    db.set(("events", "1"), {"customer_id": "c2", "kind": "click"})
    db.commit()

    expr = Field(("customer_id",), "==", "c2")
    rows = db.find(prefix=("orders",), where=expr)
    assert rows == [(("orders", "2"), {"customer_id": "c2", "amount": 20})]


def test_find_falls_back_when_no_matching_index(tmp_path: Path) -> None:
    db_path = tmp_path / "db.json"
    db = TrellisDB.create(db_path, dimensions=1)

    db.set(("1",), {"customer_id": "c1"})
    db.set(("2",), {"customer_id": "c2"})
    db.commit()

    expr = Field(("customer_id",), "==", "c2")
    rows = db.find(where=expr)
    assert rows == [(("2",), {"customer_id": "c2"})]
