"""Tests for the optional FastAPI wrapper in `trellisdb/server`.

`/init`, `/info` and `/item` live here, with the `_to_http` error mapping;
`/list` and `/find` are in `test_server_query.py`. Every request goes through
`TestClient` against a real database file under pytest's `tmp_path`; the
library itself seeds and inspects that file.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from trellisdb import TrellisDB
from trellisdb.errors import (
    LockError,
    ReadOnlyError,
    StorageCorruptionError,
    ValidationError,
)
from trellisdb.server.app import _to_http, app

DIMENSIONS = 2
WIDER_DIMENSIONS = 3
NOT_FOUND_DETAIL = "Not found"

ALICE_KEY = ["u1", "k1"]
BOB_KEY = ["u1", "k2"]
CAROL_KEY = ["u2", "k1"]
ALICE_DOC = {"customer_id": "c1", "amount": 10}
BOB_DOC = {"customer_id": "c2", "amount": 20}
CAROL_DOC = {"customer_id": "c1", "amount": 30}
SEED = {
    tuple(ALICE_KEY): ALICE_DOC,
    tuple(BOB_KEY): BOB_DOC,
    tuple(CAROL_KEY): CAROL_DOC,
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "db.json"


@pytest.fixture
def seeded(db_path: Path) -> Path:
    with TrellisDB.create(db_path, dimensions=DIMENSIONS) as db:
        for key, doc in SEED.items():
            db.set(key, doc)
        db.commit()
    return db_path


# /init


def test_init_creates_database(client: TestClient, db_path: Path) -> None:
    r = client.post("/init", params={"path": str(db_path), "dimensions": DIMENSIONS})

    assert r.status_code == status.HTTP_200_OK
    assert r.json() == {"path": str(db_path), "dimensions": DIMENSIONS, "created": True}
    assert TrellisDB.open(db_path, mode="r").dimensions == DIMENSIONS


def test_init_then_write_on_same_path_succeeds(
    client: TestClient, db_path: Path
) -> None:
    client.post("/init", params={"path": str(db_path), "dimensions": DIMENSIONS})

    r = client.post(
        "/item", params={"path": str(db_path)}, json={"coords": ALICE_KEY, "value": 1}
    )

    assert r.status_code == status.HTTP_200_OK


def test_init_refuses_existing_path_without_overwrite(
    client: TestClient, seeded: Path
) -> None:
    r = client.post("/init", params={"path": str(seeded), "dimensions": DIMENSIONS})

    assert r.status_code == status.HTTP_400_BAD_REQUEST
    assert "already exists" in r.json()["detail"]
    assert TrellisDB.open(seeded, mode="r").get(tuple(ALICE_KEY)) == ALICE_DOC


def test_init_overwrite_replaces_database(client: TestClient, seeded: Path) -> None:
    r = client.post(
        "/init",
        params={"path": str(seeded), "dimensions": WIDER_DIMENSIONS, "overwrite": True},
    )

    assert r.status_code == status.HTTP_200_OK
    assert r.json()["dimensions"] == WIDER_DIMENSIONS
    reopened = TrellisDB.open(seeded, mode="r")
    assert reopened.dimensions == WIDER_DIMENSIONS
    assert reopened.list() == []


def test_init_closes_its_writer_handle(client: TestClient, db_path: Path) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        client.post("/init", params={"path": str(db_path), "dimensions": DIMENSIONS})

    assert not [w for w in caught if issubclass(w.category, ResourceWarning)]


def test_refused_overwrite_leaves_data_intact(client: TestClient, seeded: Path) -> None:
    with TrellisDB.open(seeded, mode="rw"):
        r = client.post(
            "/init",
            params={
                "path": str(seeded),
                "dimensions": WIDER_DIMENSIONS,
                "overwrite": True,
            },
        )
    assert r.status_code == status.HTTP_423_LOCKED

    assert TrellisDB.open(seeded, mode="r").get(tuple(ALICE_KEY)) == ALICE_DOC


# /info


def test_info_reports_dimensions(client: TestClient, seeded: Path) -> None:
    r = client.get("/info", params={"path": str(seeded)})

    assert r.status_code == status.HTTP_200_OK
    assert r.json() == {"path": str(seeded), "dimensions": DIMENSIONS, "mode": "r"}


def test_info_on_missing_file_is_server_error(
    client: TestClient, db_path: Path
) -> None:
    r = client.get("/info", params={"path": str(db_path)})

    assert r.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "does not exist" in r.json()["detail"]


def test_info_on_corrupt_file_is_server_error(
    client: TestClient, db_path: Path
) -> None:
    db_path.write_text("not json", encoding="utf-8")

    r = client.get("/info", params={"path": str(db_path)})

    assert r.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "corrupted" in r.json()["detail"]


# /item


def test_set_item_commits_value(client: TestClient, seeded: Path) -> None:
    new_key = ["u3", "k1"]
    r = client.post(
        "/item",
        params={"path": str(seeded)},
        json={"coords": new_key, "value": BOB_DOC},
    )

    assert r.status_code == status.HTTP_200_OK
    assert r.json() == {"coords": new_key, "value": BOB_DOC}
    assert TrellisDB.open(seeded, mode="r").get(tuple(new_key)) == BOB_DOC


def test_set_item_with_wrong_dimension_count_is_bad_request(
    client: TestClient, seeded: Path
) -> None:
    short_key = ALICE_KEY[:1]
    r = client.post(
        "/item", params={"path": str(seeded)}, json={"coords": short_key, "value": 1}
    )

    assert r.status_code == status.HTTP_400_BAD_REQUEST
    assert r.json()["detail"] == (
        f"Expected {DIMENSIONS} key components, got {len(short_key)}"
    )


def test_set_item_body_without_coords_is_rejected_by_schema(
    client: TestClient, seeded: Path
) -> None:
    r = client.post("/item", params={"path": str(seeded)}, json={"value": 1})

    assert r.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_get_item_returns_value(client: TestClient, seeded: Path) -> None:
    r = client.get("/item", params={"path": str(seeded), "coords": BOB_KEY})

    assert r.status_code == status.HTTP_200_OK
    assert r.json() == {"coords": BOB_KEY, "value": BOB_DOC}


def test_get_missing_item_is_not_found(client: TestClient, seeded: Path) -> None:
    r = client.get("/item", params={"path": str(seeded), "coords": ["u9", "k9"]})

    assert r.status_code == status.HTTP_404_NOT_FOUND
    assert r.json() == {"detail": NOT_FOUND_DETAIL}


def test_delete_item_removes_key(client: TestClient, seeded: Path) -> None:
    r = client.request(
        "DELETE", "/item", params={"path": str(seeded)}, json={"coords": ALICE_KEY}
    )

    assert r.status_code == status.HTTP_200_OK
    assert r.json() == {"coords": ALICE_KEY, "deleted": True}
    assert not TrellisDB.open(seeded, mode="r").exists(tuple(ALICE_KEY))
    gone = client.get("/item", params={"path": str(seeded), "coords": ALICE_KEY})
    assert gone.status_code == status.HTTP_404_NOT_FOUND


def test_delete_of_missing_key_still_succeeds(client: TestClient, seeded: Path) -> None:
    # The library's delete is idempotent, so the wrapper reports success.
    missing = ["u9", "k9"]
    r = client.request(
        "DELETE", "/item", params={"path": str(seeded)}, json={"coords": missing}
    )

    assert r.status_code == status.HTTP_200_OK
    assert r.json() == {"coords": missing, "deleted": True}
    assert len(TrellisDB.open(seeded, mode="r").list()) == len(SEED)


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_write_while_another_writer_holds_the_lock_is_locked(
    client: TestClient, seeded: Path, method: str
) -> None:
    with TrellisDB.open(seeded, mode="rw"):
        r = client.request(
            method,
            "/item",
            params={"path": str(seeded)},
            json={"coords": ALICE_KEY, "value": 1},
        )

    assert r.status_code == status.HTTP_423_LOCKED
    assert "Could not acquire lock" in r.json()["detail"]
    assert TrellisDB.open(seeded, mode="r").get(tuple(ALICE_KEY)) == ALICE_DOC


def test_read_beside_a_held_writer_succeeds(client: TestClient, seeded: Path) -> None:
    with TrellisDB.open(seeded, mode="rw"):
        r = client.get("/item", params={"path": str(seeded), "coords": ALICE_KEY})

    assert r.status_code == status.HTTP_200_OK
    assert r.json()["value"] == ALICE_DOC


# _to_http


@pytest.mark.parametrize(
    ("exc", "expected_status", "expected_detail"),
    [
        (ValidationError("bad input"), status.HTTP_400_BAD_REQUEST, "bad input"),
        (ReadOnlyError("read only"), status.HTTP_400_BAD_REQUEST, "read only"),
        (KeyError("k"), status.HTTP_404_NOT_FOUND, NOT_FOUND_DETAIL),
        (LockError("held"), status.HTTP_423_LOCKED, "held"),
        (
            StorageCorruptionError("broken"),
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "broken",
        ),
        (
            Exception("anything else"),
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "anything else",
        ),
    ],
)
def test_to_http_maps_each_error_type(
    exc: Exception, expected_status: int, expected_detail: str
) -> None:
    translated = _to_http(exc)

    assert isinstance(translated, HTTPException)
    assert translated.status_code == expected_status
    assert translated.detail == expected_detail
