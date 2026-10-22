from __future__ import annotations

import multiprocessing as mp
import time
from pathlib import Path

from trellisdb import TrellisDB
from trellisdb.errors import LockError


def _writer_hold_open(db_path: str, hold_s: float) -> None:
    # Hold the writer lock for a bit.
    db = TrellisDB.open(db_path, mode="rw")
    time.sleep(hold_s)
    db.rollback()


def _writer_try_open(db_path: str, q: mp.Queue) -> None:
    try:
        db = TrellisDB.open(db_path, mode="rw")
        db.rollback()
        q.put(True)
    except LockError:
        q.put(False)


def test_two_writers_cannot_open_concurrently(tmp_path: Path) -> None:
    db_path = tmp_path / "db.json"
    # Close the creating handle first; held open, it would refuse both children
    # and the assertion below would pass for the wrong reason.
    with TrellisDB.create(db_path, dimensions=1):
        pass

    q: mp.Queue = mp.Queue()

    p1 = mp.Process(target=_writer_hold_open, args=(str(db_path), 1.5))
    p2 = mp.Process(target=_writer_try_open, args=(str(db_path), q))

    p1.start()
    # Give the first writer time to acquire the lock.
    time.sleep(0.2)
    p2.start()

    p2.join(timeout=5)
    p1.join(timeout=5)

    assert q.get(timeout=2) is False
    # The first writer really held the lock: a refused open would end it with
    # an uncaught LockError and a non-zero exit code.
    assert p1.exitcode == 0


KEY = ("a",)
VALUE = 123
DIMENSIONS = 1
CHILD_READY_TIMEOUT_S = 10.0
CHILD_JOIN_TIMEOUT_S = 10.0
QUEUE_TIMEOUT_S = 5.0


def _reader_get(db_path: str, q: mp.Queue) -> None:
    db = TrellisDB.open(db_path, mode="r")
    q.put(db.get(KEY))


def _writer_hold_until_released(
    db_path: str, q: mp.Queue, ready, release  # noqa: ANN001
) -> None:
    # Report whether the writer session really opened, then hold it.
    try:
        with TrellisDB.open(db_path, mode="rw"):
            q.put(True)
            ready.set()
            release.wait(CHILD_JOIN_TIMEOUT_S)
    except LockError:
        q.put(False)
        ready.set()


def test_reader_can_open_while_writer_session_exists(tmp_path: Path) -> None:
    db_path = tmp_path / "db.json"
    # An open parent handle would make the writer child get LockError.
    with TrellisDB.create(db_path, dimensions=DIMENSIONS) as db:
        db.set(KEY, VALUE)
        db.commit()

    writer_q: mp.Queue = mp.Queue()
    reader_q: mp.Queue = mp.Queue()
    ready = mp.Event()
    release = mp.Event()
    writer = mp.Process(
        target=_writer_hold_until_released,
        args=(str(db_path), writer_q, ready, release),
    )
    writer.start()
    try:
        assert ready.wait(CHILD_READY_TIMEOUT_S)
        assert writer_q.get(timeout=QUEUE_TIMEOUT_S) is True

        # The writer still holds its session while the reader runs.
        reader = mp.Process(target=_reader_get, args=(str(db_path), reader_q))
        reader.start()
        reader.join(CHILD_JOIN_TIMEOUT_S)
        assert reader_q.get(timeout=QUEUE_TIMEOUT_S) == VALUE
    finally:
        release.set()
        writer.join(CHILD_JOIN_TIMEOUT_S)

    assert writer.exitcode == 0
