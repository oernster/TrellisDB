from __future__ import annotations

from pathlib import Path

from trellisdb import TrellisDB


def test_slice_with_exact_match_and_wildcards(tmp_path: Path) -> None:
    db_path = tmp_path / "db.json"
    db = TrellisDB.create(db_path, dimensions=3)

    db.set(("u1", "2025", "01"), {"v": 1})
    db.set(("u1", "2025", "02"), {"v": 2})
    db.set(("u2", "2025", "01"), {"v": 3})
    db.commit()

    sliced = db.slice(("u1", None, None))
    assert sliced == {"u1": {"2025": {"01": {"v": 1}, "02": {"v": 2}}}}


def test_slice_with_membership_selector(tmp_path: Path) -> None:
    db_path = tmp_path / "db.json"
    db = TrellisDB.create(db_path, dimensions=2)

    db.set(("a", "1"), 1)
    db.set(("a", "2"), 2)
    db.set(("b", "1"), 3)
    db.commit()

    sliced = db.slice(({"a", "b"}, {"1"}))
    assert sliced == {"a": {"1": 1}, "b": {"1": 3}}
