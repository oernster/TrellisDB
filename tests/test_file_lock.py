from __future__ import annotations

from pathlib import Path
from typing import Any

import portalocker
import pytest

from trellisdb.engine.locking import FileLock, FileLockSpec, LockMode
from trellisdb.errors import LockError


def _failing_lock(seen: list[Any], error: BaseException):
    def lock(fh: Any, flags: Any) -> None:
        seen.append(fh)
        raise error

    return lock


@pytest.mark.parametrize(
    "error",
    [
        # What a Windows install without pywin32 raises for a shared lock.
        ImportError("shared locks need pywin32"),
        OSError("the lock call failed"),
    ],
)
def test_unexpected_lock_failure_closes_the_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(portalocker, "lock", _failing_lock(seen, error))
    lock = FileLock(FileLockSpec(tmp_path / "db.rw.lock", LockMode.SHARED))

    with pytest.raises(type(error)):
        lock.__enter__()

    assert seen
    assert seen[0].closed


def test_lock_timeout_closes_the_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []
    contended = portalocker.exceptions.LockException("held elsewhere")
    monkeypatch.setattr(portalocker, "lock", _failing_lock(seen, contended))
    spec = FileLockSpec(tmp_path / "db.rw.lock", LockMode.EXCLUSIVE, timeout_s=None)

    with pytest.raises(LockError):
        FileLock(spec).__enter__()

    assert seen[0].closed


def test_lock_file_can_be_locked_again_after_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "db.rw.lock"
    with monkeypatch.context() as patch:
        patch.setattr(portalocker, "lock", _failing_lock([], ImportError("no")))
        with pytest.raises(ImportError):
            FileLock(FileLockSpec(path, LockMode.EXCLUSIVE)).__enter__()

    with FileLock(FileLockSpec(path, LockMode.EXCLUSIVE)):
        pass
    path.unlink()
