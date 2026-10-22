from __future__ import annotations

import json
from pathlib import Path

import pytest

from trellisdb.engine.storage import (
    StoragePaths,
    default_payload,
    read_validated,
    recover_if_needed,
)
from trellisdb.errors import StorageCorruptionError


def test_recovery_promotes_tmp_when_main_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "db.json"
    paths = StoragePaths(db_path=db_path)

    tmp_payload = default_payload(dimensions=2)
    paths.tmp_path.write_text(json.dumps(tmp_payload), encoding="utf-8")

    recover_if_needed(paths)

    assert db_path.exists()
    assert not paths.tmp_path.exists()
    assert read_validated(db_path)["meta"]["dimensions"] == 2


def test_recovery_deletes_tmp_when_main_valid(tmp_path: Path) -> None:
    db_path = tmp_path / "db.json"
    paths = StoragePaths(db_path=db_path)

    db_path.write_text(json.dumps(default_payload(dimensions=1)), encoding="utf-8")
    paths.tmp_path.write_text(
        json.dumps(default_payload(dimensions=2)), encoding="utf-8"
    )

    recover_if_needed(paths)

    assert db_path.exists()
    assert not paths.tmp_path.exists()
    assert read_validated(db_path)["meta"]["dimensions"] == 1


def test_recovery_promotes_tmp_when_main_invalid(tmp_path: Path) -> None:
    db_path = tmp_path / "db.json"
    paths = StoragePaths(db_path=db_path)

    db_path.write_text("{not json", encoding="utf-8")
    paths.tmp_path.write_text(
        json.dumps(default_payload(dimensions=3)), encoding="utf-8"
    )

    recover_if_needed(paths)
    assert read_validated(db_path)["meta"]["dimensions"] == 3


def test_recovery_raises_when_no_valid_file_exists(tmp_path: Path) -> None:
    db_path = tmp_path / "db.json"
    paths = StoragePaths(db_path=db_path)

    db_path.write_text("{not json", encoding="utf-8")
    paths.tmp_path.write_text("{also not json", encoding="utf-8")

    with pytest.raises(StorageCorruptionError):
        recover_if_needed(paths)
