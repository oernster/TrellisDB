"""A writer open that fails must release the writer lock before it raises.

`pytest.raises` keeps the exception and its traceback, which keeps the
half-built handle alive. If the lock were freed only when that handle is
garbage collected, the second writer open would get `LockError` instead of
the real cause.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trellisdb import TrellisDB
from trellisdb.errors import StorageCorruptionError

CORRUPT_TEXT = "{not json"


def _assert_second_writer_sees_the_cause(db_path: Path) -> None:
    with pytest.raises(StorageCorruptionError) as first:
        TrellisDB.open(db_path, mode="rw")
    with pytest.raises(StorageCorruptionError):
        TrellisDB.open(db_path, mode="rw")
    assert first.value.__traceback__ is not None


def test_failed_open_of_corrupt_file_releases_writer_lock(tmp_path: Path) -> None:
    db_path = tmp_path / "db.json"
    db_path.write_text(CORRUPT_TEXT, encoding="utf-8")

    _assert_second_writer_sees_the_cause(db_path)


def test_failed_open_of_missing_file_releases_writer_lock(tmp_path: Path) -> None:
    _assert_second_writer_sees_the_cause(tmp_path / "db.json")
