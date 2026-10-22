"""On-disk storage for TrellisDB.

Design goals:

- Human-inspectable JSON on disk.
- Atomic commits via temp-file + `os.replace()`.
- Crash recovery on open by promoting a valid temp file.
"""

from __future__ import annotations

import json
import os
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict, cast

from trellisdb.errors import StorageCorruptionError, ValidationError

FORMAT_NAME = "trellisdb"
FORMAT_VERSION = 2
# Files written before the rename carry the earlier format name; they still open
# and are rewritten under FORMAT_NAME on their next commit.
READABLE_FORMAT_NAMES = (FORMAT_NAME, "axisdb")


def _utc_now_iso() -> str:
    return (
        datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


class FieldIndexDef(TypedDict):
    name: str
    path: list[str]


class IndexMeta(TypedDict, total=False):
    prefix: dict[str, Any]
    fields: list[FieldIndexDef]


class Meta(TypedDict):
    dimensions: int
    created_at: str
    updated_at: str
    indexes: IndexMeta


class IndexPayload(TypedDict, total=False):
    prefix_keys: list[str]
    fields: dict[str, dict[str, list[str]]]


class DBPayload(TypedDict):
    format: str
    format_version: int
    meta: Meta
    data: dict[str, Any]
    index: IndexPayload


@dataclass(frozen=True)
class StoragePaths:
    db_path: Path

    @property
    def tmp_path(self) -> Path:
        return self.db_path.with_suffix(self.db_path.suffix + ".tmp")


def default_payload(dimensions: int) -> DBPayload:
    if dimensions <= 0:
        raise ValidationError("dimensions must be a positive integer")

    now = _utc_now_iso()
    return {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "meta": {
            "dimensions": dimensions,
            "created_at": now,
            "updated_at": now,
            "indexes": {"prefix": {"enabled": True}, "fields": []},
        },
        "data": {},
        "index": {"prefix_keys": [], "fields": {}},
    }


def _is_dict(value: Any) -> bool:
    return isinstance(value, dict)


def validate_payload(raw: Any) -> DBPayload:
    if not _is_dict(raw):
        raise ValidationError("DB file must contain a JSON object")

    fmt = raw.get("format")
    ver = raw.get("format_version")
    if fmt not in READABLE_FORMAT_NAMES or ver != FORMAT_VERSION:
        raise ValidationError("Unsupported DB format or version")

    meta = raw.get("meta")
    if not _is_dict(meta):
        raise ValidationError("Missing or invalid meta")

    try:
        dimensions = int(meta["dimensions"])
    except Exception as exc:  # noqa: BLE001
        raise ValidationError("Missing or invalid meta.dimensions") from exc
    if dimensions <= 0:
        raise ValidationError("meta.dimensions must be a positive integer")

    for k in ("created_at", "updated_at"):
        if not isinstance(meta.get(k), str):
            raise ValidationError(f"Missing or invalid meta.{k}")

    indexes = meta.get("indexes")
    if indexes is None:
        indexes = {"prefix": {"enabled": True}, "fields": []}
        meta["indexes"] = indexes
    if not _is_dict(indexes):
        raise ValidationError("Missing or invalid meta.indexes")

    data = raw.get("data")
    if not _is_dict(data):
        raise ValidationError("Missing or invalid data")

    index = raw.get("index")
    if index is None:
        index = {"prefix_keys": [], "fields": {}}
        raw["index"] = index
    if not _is_dict(index):
        raise ValidationError("Missing or invalid index")

    # Soft-validate index structure for MVP: allow empty/missing fields.
    if "prefix_keys" in index and not isinstance(index["prefix_keys"], list):
        raise ValidationError("index.prefix_keys must be a list")
    if "fields" in index and not _is_dict(index["fields"]):
        raise ValidationError("index.fields must be an object")

    # Cast after validation.
    return cast(DBPayload, raw)


def _read_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise StorageCorruptionError(f"Could not read DB file: {path}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise StorageCorruptionError(f"Invalid JSON in DB file: {path}") from exc


def read_validated(path: Path) -> DBPayload:
    return validate_payload(_read_json(path))


def recover_if_needed(paths: StoragePaths) -> None:
    """Best-effort recovery.

    Rules:
    - If main is missing and tmp exists+valid: promote tmp.
    - If main invalid and tmp exists+valid: promote tmp.
    - If main valid and tmp exists: delete tmp.
    """

    main_exists = paths.db_path.exists()
    tmp_exists = paths.tmp_path.exists()

    if not main_exists and not tmp_exists:
        return

    main_ok = False
    if main_exists:
        try:
            read_validated(paths.db_path)
            main_ok = True
        except (ValidationError, StorageCorruptionError):
            main_ok = False

    tmp_ok = False
    if tmp_exists:
        try:
            read_validated(paths.tmp_path)
            tmp_ok = True
        except (ValidationError, StorageCorruptionError):
            tmp_ok = False

    if main_ok:
        if tmp_exists:
            with suppress(OSError):
                paths.tmp_path.unlink()
        return

    if tmp_ok:
        os.replace(paths.tmp_path, paths.db_path)
        return

    if main_exists:
        raise StorageCorruptionError(
            f"DB file is corrupted and no valid recovery file exists: {paths.db_path}"
        )
    raise StorageCorruptionError(
        f"DB file is missing and temp file is not a valid recovery: {paths.db_path}"
    )


def _fsync_file(f) -> None:  # noqa: ANN001
    f.flush()
    os.fsync(f.fileno())


def _fsync_dir_best_effort(path: Path) -> None:
    """Attempt to fsync the directory containing `path`.

    On Windows this may not be supported; treat it as best-effort.
    """

    directory = path.parent
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        return
    finally:
        os.close(fd)


def write_atomic(paths: StoragePaths, payload: DBPayload) -> None:
    """Write payload to tmp and atomically replace main."""

    payload["meta"]["updated_at"] = _utc_now_iso()

    tmp = paths.tmp_path
    tmp.parent.mkdir(parents=True, exist_ok=True)

    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(encoded)
            _fsync_file(f)
    except OSError as exc:
        raise StorageCorruptionError(f"Failed to write temp DB file: {tmp}") from exc

    os.replace(tmp, paths.db_path)
    _fsync_dir_best_effort(paths.db_path)
