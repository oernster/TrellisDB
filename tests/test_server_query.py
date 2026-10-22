"""Tests for the `/list` and `/find` endpoints of the FastAPI wrapper.

`prefix` and `field` are repeated query parameters, as the README documents
(`?prefix=u1&field=customer_id`); every test sends them in the query string.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from trellisdb import TrellisDB
from trellisdb.server.app import app

DIMENSIONS = 2
FIND_LIMIT = 1
LIST_DEPTH = 1

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
U1_PREFIX = ALICE_KEY[:1]


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def seeded(tmp_path: Path) -> Path:
    db_path = tmp_path / "db.json"
    with TrellisDB.create(db_path, dimensions=DIMENSIONS) as db:
        for key, doc in SEED.items():
            db.set(key, doc)
        db.commit()
    return db_path


def _rows(*pairs: tuple[list[str], dict[str, object]]) -> dict[str, object]:
    return {"rows": [{"key": key, "value": doc} for key, doc in pairs]}


# /list


def test_list_returns_every_key(client: TestClient, seeded: Path) -> None:
    r = client.get("/list", params={"path": str(seeded)})

    assert r.status_code == status.HTTP_200_OK
    assert r.json() == {"keys": [ALICE_KEY, BOB_KEY, CAROL_KEY]}


def test_list_reads_prefix_from_query_string(client: TestClient, seeded: Path) -> None:
    r = client.get("/list", params={"path": str(seeded), "prefix": U1_PREFIX})

    assert r.status_code == status.HTTP_200_OK
    assert r.json() == {"keys": [ALICE_KEY, BOB_KEY]}


def test_list_with_depth_truncates_and_deduplicates(
    client: TestClient, seeded: Path
) -> None:
    r = client.get("/list", params={"path": str(seeded), "depth": LIST_DEPTH})

    assert r.status_code == status.HTTP_200_OK
    assert r.json() == {"keys": [U1_PREFIX, CAROL_KEY[:LIST_DEPTH]]}


def test_list_with_prefix_and_depth(client: TestClient, seeded: Path) -> None:
    r = client.get(
        "/list",
        params={"path": str(seeded), "prefix": U1_PREFIX, "depth": LIST_DEPTH},
    )

    assert r.json() == {"keys": [ALICE_KEY, BOB_KEY]}


def test_list_prefix_longer_than_dimensions_is_bad_request(
    client: TestClient, seeded: Path
) -> None:
    too_long = ALICE_KEY + ["extra"]
    r = client.get("/list", params={"path": str(seeded), "prefix": too_long})

    assert r.status_code == status.HTTP_400_BAD_REQUEST
    assert r.json()["detail"] == "prefix longer than number of dimensions"


# /find


def test_find_without_predicate_returns_every_row(
    client: TestClient, seeded: Path
) -> None:
    r = client.get("/find", params={"path": str(seeded)})

    assert r.status_code == status.HTTP_200_OK
    assert r.json() == _rows(
        (ALICE_KEY, ALICE_DOC), (BOB_KEY, BOB_DOC), (CAROL_KEY, CAROL_DOC)
    )


def test_find_reads_field_from_query_string(client: TestClient, seeded: Path) -> None:
    r = client.get(
        "/find",
        params={"path": str(seeded), "field": ["customer_id"], "value": "c1"},
    )

    assert r.status_code == status.HTTP_200_OK
    assert r.json() == _rows((ALICE_KEY, ALICE_DOC), (CAROL_KEY, CAROL_DOC))


def test_find_with_field_predicate_and_other_operator(
    client: TestClient, seeded: Path
) -> None:
    r = client.get(
        "/find",
        params={
            "path": str(seeded),
            "field": ["customer_id"],
            "op": "!=",
            "value": "c1",
        },
    )

    assert r.json() == _rows((BOB_KEY, BOB_DOC))


def test_find_with_prefix(client: TestClient, seeded: Path) -> None:
    r = client.get("/find", params={"path": str(seeded), "prefix": U1_PREFIX})

    assert r.json() == _rows((ALICE_KEY, ALICE_DOC), (BOB_KEY, BOB_DOC))


def test_find_with_limit(client: TestClient, seeded: Path) -> None:
    r = client.get("/find", params={"path": str(seeded), "limit": FIND_LIMIT})

    assert r.status_code == status.HTTP_200_OK
    assert r.json() == _rows((ALICE_KEY, ALICE_DOC))


def test_find_with_non_positive_limit_is_bad_request(
    client: TestClient, seeded: Path
) -> None:
    r = client.get("/find", params={"path": str(seeded), "limit": 0})

    assert r.status_code == status.HTTP_400_BAD_REQUEST
    assert r.json()["detail"] == "limit must be a positive integer"


# /find value decoding: JSON when it parses, the raw string otherwise.

TYPED_FIELD = "v"
TYPED_SEED = {
    "int": 10,
    "number_string": "10",
    "float": 10.5,
    "true": True,
    "false": False,
    "null": None,
    "word": "c1",
}


@pytest.fixture
def typed(tmp_path: Path) -> Path:
    db_path = tmp_path / "typed.json"
    with TrellisDB.create(db_path, dimensions=DIMENSIONS) as db:
        for name, literal in TYPED_SEED.items():
            db.set(("t", name), {TYPED_FIELD: literal})
        db.commit()
    return db_path


@pytest.mark.parametrize(
    ("raw", "expected_name"),
    [
        ("10", "int"),
        ('"10"', "number_string"),
        ("10.5", "float"),
        ("true", "true"),
        ("false", "false"),
        ("null", "null"),
        ("c1", "word"),
    ],
)
def test_find_decodes_value_as_json_or_keeps_the_string(
    client: TestClient, typed: Path, raw: str, expected_name: str
) -> None:
    r = client.get(
        "/find",
        params={"path": str(typed), "field": [TYPED_FIELD], "value": raw},
    )

    assert r.status_code == status.HTTP_200_OK
    expected_doc = {TYPED_FIELD: TYPED_SEED[expected_name]}
    assert r.json() == _rows((["t", expected_name], expected_doc))


def test_find_on_missing_file_is_server_error(
    client: TestClient, tmp_path: Path
) -> None:
    r = client.get("/find", params={"path": str(tmp_path / "missing.json")})

    assert r.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert "does not exist" in r.json()["detail"]
