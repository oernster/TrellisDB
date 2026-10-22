from __future__ import annotations

import json
from pathlib import Path

import pytest

from trellisdb import TrellisDB
from trellisdb.engine.storage import (
    FORMAT_NAME,
    READABLE_FORMAT_NAMES,
    default_payload,
    read_validated,
)
from trellisdb.errors import ValidationError

LEGACY_FORMAT_NAMES = tuple(n for n in READABLE_FORMAT_NAMES if n != FORMAT_NAME)


def _write_payload(db_path: Path, format_name: str) -> None:
    payload = default_payload(dimensions=1)
    payload["format"] = format_name
    db_path.write_text(json.dumps(payload), encoding="utf-8")


def test_new_files_carry_the_current_format_name(tmp_path: Path) -> None:
    db_path = tmp_path / "db.json"
    with TrellisDB.create(db_path, dimensions=1):
        pass

    assert json.loads(db_path.read_text(encoding="utf-8"))["format"] == FORMAT_NAME


@pytest.mark.parametrize("legacy_name", LEGACY_FORMAT_NAMES)
def test_legacy_file_opens_and_is_rewritten_on_commit(
    tmp_path: Path, legacy_name: str
) -> None:
    db_path = tmp_path / "db.json"
    _write_payload(db_path, legacy_name)

    with TrellisDB.open(db_path) as db:
        db.set(("a",), {"v": 1})
        db.commit()

    assert read_validated(db_path)["format"] == FORMAT_NAME
    with TrellisDB.open(db_path, mode="r") as ro:
        assert ro.get(("a",)) == {"v": 1}


def test_unknown_format_name_is_refused(tmp_path: Path) -> None:
    db_path = tmp_path / "db.json"
    _write_payload(db_path, "not-a-known-format")

    with pytest.raises(ValidationError):
        read_validated(db_path)


def test_a_legacy_format_name_is_still_readable() -> None:
    assert LEGACY_FORMAT_NAMES
