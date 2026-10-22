"""Cross-platform file locking primitives.

The storage design requires:

- A single-writer lock held for the lifetime of a writer session.
- A read/write lock used as shared during reads and exclusive during commits.
"""

from __future__ import annotations

import os
import time
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import portalocker

from trellisdb.errors import LockError


class LockMode(str, Enum):
    SHARED = "shared"
    EXCLUSIVE = "exclusive"


@dataclass(frozen=True)
class FileLockSpec:
    path: Path
    mode: LockMode
    timeout_s: float | None = 10.0


class FileLock(AbstractContextManager["FileLock"]):
    """A context-managed file lock using portalocker."""

    def __init__(self, spec: FileLockSpec) -> None:
        self._spec = spec
        self._fh = None

    def __enter__(self) -> FileLock:
        flags = (
            portalocker.LOCK_SH
            if self._spec.mode == LockMode.SHARED
            else portalocker.LOCK_EX
        )
        flags |= portalocker.LOCK_NB

        self._spec.path.parent.mkdir(parents=True, exist_ok=True)

        # Open our own handle so we can control retry behavior.
        # Avoid append-mode on Windows because some lock implementations are
        # sensitive to how the handle was opened.
        if self._spec.path.exists():
            self._fh = open(self._spec.path, "r+b")
        else:
            self._fh = open(self._spec.path, "w+b")
            # Ensure non-empty content.
            self._fh.write(b"0")
            self._fh.flush()
            with suppress(OSError):
                os.fsync(self._fh.fileno())

        self._fh.seek(0)

        deadline = None
        if self._spec.timeout_s is not None:
            deadline = time.monotonic() + float(self._spec.timeout_s)

        while True:
            try:
                portalocker.lock(self._fh, flags)
                break
            except portalocker.exceptions.LockException as exc:
                if deadline is None or time.monotonic() >= deadline:
                    self._fh.close()
                    self._fh = None
                    raise LockError(
                        f"Could not acquire lock: {self._spec.path}"
                    ) from exc
                time.sleep(0.05)

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        if self._fh is not None:
            try:
                portalocker.unlock(self._fh)
            finally:
                self._fh.close()
                self._fh = None


@dataclass(frozen=True)
class LockPaths:
    """Derive lock file paths from the main database path."""

    db_path: Path

    @property
    def writer_lock(self) -> Path:
        return self.db_path.with_suffix(self.db_path.suffix + ".writer.lock")

    @property
    def rw_lock(self) -> Path:
        return self.db_path.with_suffix(self.db_path.suffix + ".rw.lock")
