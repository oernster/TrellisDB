"""`TrellisDB.create(..., overwrite=True)` must not touch a database another writer holds.

`create` takes the exclusive writer lock before it writes the new file, so a
refused overwrite raises `LockError` and leaves the existing data in place.
The first test holds the writer in this process; the second holds it in a
real child process, as `test_locking_multiprocess.py` does.
"""

from __future__ import annotations

import multiprocessing as mp
from pathlib import Path

import pytest

from trellisdb import TrellisDB
from trellisdb.errors import LockError

DIMENSIONS = 1
WIDER_DIMENSIONS = 2
KEY = ("a",)
VALUE = 123
CHILD_READY_TIMEOUT_S = 10.0
CHILD_JOIN_TIMEOUT_S = 10.0


def _seed(db_path: Path) -> None:
    with TrellisDB.create(db_path, dimensions=DIMENSIONS) as db:
        db.set(KEY, VALUE)
        db.commit()


def _assert_untouched(db_path: Path) -> None:
    reopened = TrellisDB.open(db_path, mode="r")
    assert reopened.dimensions == DIMENSIONS
    assert reopened.get(KEY) == VALUE


def test_refused_overwrite_in_same_process_leaves_data_intact(tmp_path: Path) -> None:
    db_path = tmp_path / "db.json"
    _seed(db_path)

    with TrellisDB.open(db_path, mode="rw"), pytest.raises(LockError):
        TrellisDB.create(db_path, dimensions=WIDER_DIMENSIONS, overwrite=True)

    _assert_untouched(db_path)


def _hold_writer_until_released(db_path: str, ready, release) -> None:  # noqa: ANN001
    with TrellisDB.open(db_path, mode="rw"):
        ready.set()
        release.wait(CHILD_JOIN_TIMEOUT_S)


def test_refused_overwrite_across_processes_leaves_data_intact(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "db.json"
    _seed(db_path)

    ready = mp.Event()
    release = mp.Event()
    holder = mp.Process(
        target=_hold_writer_until_released, args=(str(db_path), ready, release)
    )
    holder.start()
    try:
        assert ready.wait(CHILD_READY_TIMEOUT_S)
        with pytest.raises(LockError):
            TrellisDB.create(db_path, dimensions=WIDER_DIMENSIONS, overwrite=True)
        _assert_untouched(db_path)
    finally:
        release.set()
        holder.join(CHILD_JOIN_TIMEOUT_S)

    assert holder.exitcode == 0
    _assert_untouched(db_path)
