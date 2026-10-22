"""Public API for TrellisDB.

This module intentionally keeps the public surface small and typed.
Engine details live in [`trellisdb.engine.storage`](trellisdb/engine/storage.py:1),
[`trellisdb.engine.locking`](trellisdb/engine/locking.py:1) and other `trellisdb.*` modules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from trellisdb.engine.keycodec import decode_key, encode_key
from trellisdb.engine.locking import FileLock, FileLockSpec, LockMode, LockPaths
from trellisdb.engine.storage import (
    DBPayload,
    FieldIndexDef,
    StoragePaths,
    default_payload,
    read_validated,
    recover_if_needed,
    write_atomic,
)
from trellisdb.errors import (
    InvalidCoordsError,
    NonJsonSerializableValueError,
    ReadOnlyError,
    StorageCorruptionError,
    ValidationError,
    WrongDimensionLengthError,
)
from trellisdb.index.fields import canonical_value_key, rebuild_field_indexes
from trellisdb.index.prefix import rebuild_prefix_keys, select_prefix_range
from trellisdb.query.ast import Expr, Field, is_simple_field_equality
from trellisdb.query.eval import evaluate

OpenMode = Literal["r", "rw"]


@dataclass
class TrellisDB:
    """Main database handle.

    Implementation is added incrementally; this file is the stable public
    surface that other interfaces (CLI, server) will use.
    """

    path: Path
    mode: OpenMode = "rw"
    lock: bool = True

    _dimensions: int = field(init=False)
    _base_data: dict[str, Any] = field(init=False, default_factory=dict)
    _base_prefix_keys: list[str] = field(init=False, default_factory=list)
    _base_field_indexes: dict[str, dict[str, list[str]]] = field(
        init=False, default_factory=dict
    )
    _field_index_defs: list[FieldIndexDef] = field(init=False, default_factory=list)

    _overlay_set: dict[str, Any] = field(init=False, default_factory=dict)
    _overlay_del: set[str] = field(init=False, default_factory=set)

    _writer_lock: FileLock | None = field(init=False, default=None)
    _lock_paths: LockPaths = field(init=False)
    _storage_paths: StoragePaths = field(init=False)

    @classmethod
    def open(
        cls, path: str | Path, mode: OpenMode = "rw", lock: bool = True
    ) -> TrellisDB:
        db = cls(path=Path(path), mode=mode, lock=lock)
        db._initialize()
        return db

    @classmethod
    def create(
        cls,
        path: str | Path,
        *,
        dimensions: int,
        overwrite: bool = False,
        lock: bool = True,
    ) -> TrellisDB:
        """Create a new database file.

        This is a convenience helper (not part of the minimal API shape in the spec),
        required to bootstrap a database because dimensions are fixed at creation time.
        """

        p = Path(path)
        if p.exists() and not overwrite:
            raise ValidationError(f"Database already exists: {p}")

        payload = default_payload(dimensions=dimensions)
        db = cls(path=p, mode="rw", lock=lock)
        db._initialize(initial_payload=payload)
        return db

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def define_field_index(self, name: str, path: tuple[str, ...] | list[str]) -> None:
        """Define a field index stored in DB metadata and rebuilt on commit.

        This is a correctness-first MVP feature:
        - Indexes are rebuilt on each commit.
        - `find()` can use the index for simple `Field(path) == literal` queries.
        """

        self._assert_writable()
        if not name or not isinstance(name, str):
            raise ValidationError("index name must be a non-empty string")
        if not isinstance(path, (list, tuple)) or not all(
            isinstance(p, str) for p in path
        ):
            raise ValidationError("index path must be a list/tuple of strings")

        idx: FieldIndexDef = {"name": name, "path": list(path)}

        # Replace existing definition with same name.
        self._field_index_defs = [
            d for d in self._field_index_defs if d["name"] != name
        ]
        self._field_index_defs.append(idx)

    def __enter__(self) -> TrellisDB:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> None:
        if self.mode == "rw":
            # Safety: never auto-commit.
            self.rollback()
        if self._writer_lock is not None:
            self._writer_lock.__exit__(exc_type, exc, tb)
            self._writer_lock = None
        return None

    # ---------------------------------------------------------------------
    # Initialization
    # ---------------------------------------------------------------------

    def _initialize(self, initial_payload: DBPayload | None = None) -> None:
        # `create` passes `initial_payload`; it is written only once the writer
        # lock is held, so a refused create leaves an existing file untouched.
        self._lock_paths = LockPaths(self.path)
        self._storage_paths = StoragePaths(db_path=self.path)

        # If locking is enabled and we're a writer, enforce single-writer.
        if self.lock and self.mode == "rw":
            self._writer_lock = FileLock(
                # Fail fast if another writer already exists.
                FileLockSpec(
                    self._lock_paths.writer_lock,
                    LockMode.EXCLUSIVE,
                    timeout_s=0.0,
                )
            )
            self._writer_lock.__enter__()

        try:
            # Recovery should be performed with exclusive rw lock to avoid races.
            if self.lock:
                rw_spec = FileLockSpec(self._lock_paths.rw_lock, LockMode.EXCLUSIVE)
                with FileLock(rw_spec):
                    self._write_initial_then_recover(initial_payload)
            else:
                self._write_initial_then_recover(initial_payload)

            self._reload_base_from_disk()
        except BaseException:
            # Release now, not when the half-built handle is garbage collected.
            if self._writer_lock is not None:
                self._writer_lock.__exit__(None, None, None)
                self._writer_lock = None
            raise

    def _write_initial_then_recover(self, initial_payload: DBPayload | None) -> None:
        if initial_payload is not None:
            write_atomic(self._storage_paths, initial_payload)
        recover_if_needed(self._storage_paths)

    def _reload_base_from_disk(self) -> None:
        if not self.path.exists():
            raise StorageCorruptionError(f"Database file does not exist: {self.path}")

        if self.lock:
            lock_mode = LockMode.SHARED
            with FileLock(FileLockSpec(self._lock_paths.rw_lock, lock_mode)):
                payload = read_validated(self.path)
        else:
            payload = read_validated(self.path)

        self._dimensions = int(payload["meta"]["dimensions"])
        self._base_data = dict(payload.get("data", {}))
        index_payload = payload.get("index", {})
        self._base_prefix_keys = list(index_payload.get("prefix_keys", []))
        self._base_field_indexes = dict(index_payload.get("fields", {}))
        self._field_index_defs = list(
            payload["meta"].get("indexes", {}).get("fields", [])
        )

        # Clear overlays after a reload.
        self._overlay_set.clear()
        self._overlay_del.clear()

    def _assert_writable(self) -> None:
        if self.mode != "rw":
            raise ReadOnlyError("Database opened in read-only mode")

    def _assert_key(self, key: tuple[str, ...]) -> None:
        if not isinstance(key, tuple):
            raise InvalidCoordsError("Key must be a tuple[str, ...]")
        if not all(isinstance(c, str) for c in key):
            raise InvalidCoordsError("All key components must be strings")
        if len(key) != self._dimensions:
            raise WrongDimensionLengthError(
                f"Expected {self._dimensions} key components, got {len(key)}"
            )

    # ---------------------------------------------------------------------
    # CRUD
    # ---------------------------------------------------------------------

    def get(self, key: tuple[str, ...]) -> Any:
        self._assert_key(key)
        ek = encode_key(key)

        if ek in self._overlay_del:
            raise KeyError(key)
        if ek in self._overlay_set:
            return self._overlay_set[ek]

        if self.mode == "r":
            # Read-only uses fresh reads per call.
            self._reload_base_from_disk()

        return self._base_data[ek]

    def set(self, key: tuple[str, ...], value: Any) -> None:
        self._assert_writable()
        self._assert_key(key)

        # Ensure JSON-serializable by default.
        try:
            json.dumps(value)
        except TypeError as exc:
            raise NonJsonSerializableValueError(
                "Value is not JSON-serializable"
            ) from exc

        ek = encode_key(key)
        self._overlay_set[ek] = value
        self._overlay_del.discard(ek)

    def delete(self, key: tuple[str, ...]) -> None:
        self._assert_writable()
        self._assert_key(key)
        ek = encode_key(key)

        if ek in self._overlay_set:
            del self._overlay_set[ek]
        self._overlay_del.add(ek)

    def exists(self, key: tuple[str, ...]) -> bool:
        self._assert_key(key)
        ek = encode_key(key)
        if ek in self._overlay_del:
            return False
        if ek in self._overlay_set:
            return True
        if self.mode == "r":
            self._reload_base_from_disk()
        return ek in self._base_data

    # ---------------------------------------------------------------------
    # Listing / Querying
    # ---------------------------------------------------------------------

    def list(
        self, prefix: tuple[str, ...] | None = None, depth: int | None = None
    ) -> list[tuple[str, ...]]:
        """List keys.

        - `prefix` filters by key-prefix.
        - `depth` limits returned key length relative to prefix.
        """

        if prefix is None:
            prefix = ()
        if len(prefix) > self._dimensions:
            raise ValidationError("prefix longer than number of dimensions")

        if self.mode == "r":
            self._reload_base_from_disk()

        keys = self._materialized_keys()
        if prefix:
            ep = encode_key(prefix)
            keys = [k for k in keys if k.startswith(ep + "/") or k == ep]

        out: list[tuple[str, ...]] = []
        for ek in keys:
            dk = decode_key(ek)
            if depth is not None:
                max_len = len(prefix) + depth
                dk = dk[:max_len]
            out.append(dk)

        # Deduplicate if depth truncation caused collisions.
        return sorted(set(out))

    def slice(self, dim_slices: object) -> object:
        """Return a nested dict slice based on per-dimension selectors.

        `dim_slices` is a sequence with up to N elements (N == dimensions).
        If shorter than N, it is padded with `None` (wildcards).

        Each selector may be:
        - None: wildcard
        - str: exact match
        - list/tuple/set of str: membership match
        - callable: predicate on the dimension component (slower)
        """

        if self.mode == "r":
            self._reload_base_from_disk()

        selectors = self._normalize_dim_slices(dim_slices)

        out: dict[str, Any] = {}
        for encoded_key in self._materialized_keys():
            key = decode_key(encoded_key)
            if not self._match_dim_slices(selectors, key):
                continue

            node: dict[str, Any] = out
            for comp in key[:-1]:
                nxt = node.get(comp)
                if not isinstance(nxt, dict):
                    nxt = {}
                    node[comp] = nxt
                node = nxt
            node[key[-1]] = self._get_by_encoded_key(encoded_key)

        return out

    def _normalize_dim_slices(self, dim_slices: object) -> tuple[object, ...]:
        if not isinstance(dim_slices, (list, tuple)):
            raise ValidationError("dim_slices must be a list/tuple")
        if len(dim_slices) > self._dimensions:
            raise ValidationError("dim_slices longer than number of dimensions")
        padded = tuple(dim_slices) + (None,) * (self._dimensions - len(dim_slices))
        return padded

    def _match_dim_slices(
        self, selectors: tuple[object, ...], key: tuple[str, ...]
    ) -> bool:
        for selector, comp in zip(selectors, key, strict=True):
            if selector is None:
                continue
            if isinstance(selector, str):
                if comp != selector:
                    return False
                continue
            if isinstance(selector, (list, tuple, set)):
                if comp not in selector:
                    return False
                continue
            if callable(selector):
                if not bool(selector(comp)):
                    return False
                continue
            raise ValidationError(
                "Invalid dim_slices selector (expected None, str, list/tuple/set or callable)"
            )
        return True

    def find(
        self,
        prefix: tuple[str, ...] | None = None,
        where: Expr | None | object = None,
        limit: int | None = None,
    ) -> list[tuple[tuple[str, ...], Any]]:
        if prefix is None:
            prefix = ()
        if len(prefix) > self._dimensions:
            raise ValidationError("prefix longer than number of dimensions")
        if limit is not None and limit <= 0:
            raise ValidationError("limit must be a positive integer")

        if self.mode == "r":
            self._reload_base_from_disk()

        candidates = self._candidate_keys(prefix=prefix, where=where)
        results: list[tuple[tuple[str, ...], Any]] = []
        for ek in candidates:
            doc = self._get_by_encoded_key(ek)
            if where is None:
                ok = True
            elif isinstance(where, Expr):
                ok = evaluate(where, encoded_key=ek, value=doc)
            elif callable(where):
                ok = bool(where(doc))
            else:
                raise ValidationError("where must be an Expr or callable")

            if ok:
                results.append((decode_key(ek), doc))
                if limit is not None and len(results) >= limit:
                    break
        return results

    def _candidate_keys(self, prefix: tuple[str, ...], where: object) -> list[str]:
        """Return candidate encoded keys.

        Optimizations (correctness-first):
        - Uses prefix index when available.
        - Uses field index for simple `Field(path) == literal` queries when configured.
        """

        all_keys = self._materialized_keys()

        # Base-only index usage is only safe when there is no overlay.
        can_use_indexes = (
            not self._overlay_set and not self._overlay_del and self._base_prefix_keys
        )

        # 1) Field index (if enabled and query is simple equality)
        if (
            can_use_indexes
            and isinstance(where, Expr)
            and is_simple_field_equality(where)
            and isinstance(where, Field)
        ):
            # Find the configured index with an identical path.
            index_name = None
            for d in self._field_index_defs:
                if tuple(d["path"]) == tuple(where.path):
                    index_name = d["name"]
                    break

            if index_name is not None:
                vkey = canonical_value_key(where.value)
                candidates = self._base_field_indexes.get(index_name, {}).get(vkey, [])

                # Apply prefix restriction on top.
                if prefix:
                    ep = encode_key(prefix)
                    return [k for k in candidates if k.startswith(ep + "/") or k == ep]
                return list(candidates)

        # 2) Prefix index
        if prefix:
            if can_use_indexes:
                ep = encode_key(prefix)
                lo, hi = select_prefix_range(self._base_prefix_keys, ep)
                return self._base_prefix_keys[lo:hi]

            ep = encode_key(prefix)
            return [k for k in all_keys if k.startswith(ep + "/") or k == ep]

        return all_keys

    def _materialized_keys(self) -> list[str]:
        keys = set(self._base_data.keys())
        keys.difference_update(self._overlay_del)
        keys.update(self._overlay_set.keys())
        return sorted(keys)

    def _get_by_encoded_key(self, encoded_key: str) -> Any:
        if encoded_key in self._overlay_del:
            raise KeyError(encoded_key)
        if encoded_key in self._overlay_set:
            return self._overlay_set[encoded_key]
        return self._base_data[encoded_key]

    # ---------------------------------------------------------------------
    # Transactions
    # ---------------------------------------------------------------------

    def commit(self) -> None:
        self._assert_writable()

        # Nothing to do.
        if not self._overlay_set and not self._overlay_del:
            return

        # Build next state.
        next_data = dict(self._base_data)
        for ek in self._overlay_del:
            next_data.pop(ek, None)
        next_data.update(self._overlay_set)

        # Rebuild indexes (correctness-first).
        prefix_keys = rebuild_prefix_keys(next_data)
        field_indexes = rebuild_field_indexes(next_data, self._field_index_defs)

        payload = default_payload(dimensions=self._dimensions)
        payload["meta"]["indexes"]["fields"] = self._field_index_defs
        payload["data"] = next_data
        payload["index"] = {"prefix_keys": prefix_keys, "fields": field_indexes}

        if self.lock:
            with FileLock(FileLockSpec(self._lock_paths.rw_lock, LockMode.EXCLUSIVE)):
                write_atomic(self._storage_paths, payload)
        else:
            write_atomic(self._storage_paths, payload)

        # Refresh base and clear overlay.
        self._base_data = next_data
        self._base_prefix_keys = prefix_keys
        self._base_field_indexes = field_indexes
        self._overlay_set.clear()
        self._overlay_del.clear()

    def rollback(self) -> None:
        if self.mode == "r":
            return
        self._reload_base_from_disk()
