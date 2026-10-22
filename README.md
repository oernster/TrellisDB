# TrellisDB

**TrellisDB** is a tiny embedded document database for Python, designed for simple, reliable storage of JSON documents addressed by **N-dimensional coordinate keys**.

It is library-first, requires no server and stores all data in a single JSON file with atomic, crash-safe commits.

<img width="1764" height="987" alt="TrellisDB" src="https://github.com/user-attachments/assets/8c3e56ae-2a0b-4ecc-b0b9-f35780e73bef" />

> **See also:**  
> [USE_CASES.md](https://github.com/oernster/TrellisDB/blob/main/USE_CASES.md): a concise overview of practical applications and patterns enabled by this multidimensional JSON storage model.  
> [ARCHITECTURE.md](https://github.com/oernster/TrellisDB/blob/main/ARCHITECTURE.md): the engine, the storage format and the locking model.  
> [TECH_DEBT.md](https://github.com/oernster/TrellisDB/blob/main/TECH_DEBT.md): what is still open, what is deliberately left and what only looks like debt.

> **MIT licensed.** TrellisDB is free and open source under the MIT licence, so it can be imported into closed-source and commercial code with no further agreement. Releases up to and including 1.0.6 were published under GPL-3.0 and stay under it.

---

## Key properties

- Library-first design (usable without any server)
- Single-file JSON storage
- Atomic, crash-safe commits via temp-file replace
- Safe multi-process access (single writer, multiple readers) via file locks
- Minimal but useful query + indexing support (correctness-first)

---

## Features

- Embedded JSON document database
- N-dimensional coordinate keys
- Atomic commit and recovery
- Key listing (`list`) and multidimensional slicing (`slice`)
- Basic querying (`find`) with optional persisted field indexes
- Optional FastAPI wrapper with Swagger (`/docs`) and ReDoc (`/redoc`)

---

## Installation

### Core library

```bash
pip install trellisdb
```

### Optional server components

```bash
pip install "trellisdb[server]"
```

---

## Basic library usage

Create a database, write a value and commit:

```python
from trellisdb import TrellisDB

db = TrellisDB.create("./mydb.json", dimensions=2)
db.set(("user1", "orders"), {"count": 3})
db.commit()

ro = TrellisDB.open("./mydb.json", mode="r")
print(ro.get(("user1", "orders")))
```

Notes:

- **Dimensions are fixed** at database creation time; all keys must be a `tuple[str, ...]` of that length.
- Values must be **JSON-serializable** (validated by default on `set`).
- `mode="rw"` writes are staged in-memory until `commit()`; `rollback()` discards uncommitted changes.
- `mode="r"` reloads from disk on each operation to reflect the latest committed state.

---

## Query and indexing (MVP)

TrellisDB is optimized for correctness and predictable behavior over complex query planning.

- Indexes are **materialized and persisted** in the DB file.
- Indexes are **rebuilt on each commit** (correctness-first MVP).
- `find()` can use indexes only when there are **no pending writes in the current session**.

### Index types

- **Prefix index**: always maintained; used by `find(prefix=...)` to reduce scan work
  (note: `list(prefix=...)` currently filters materialized keys directly).
- **Field indexes**: optional, user-defined; can accelerate simple equality predicates of the form
  `Field(("path", "to", "field"), "==", literal)`.

Define a field index:

```python
from trellisdb import TrellisDB

db = TrellisDB.create("./mydb.json", dimensions=2)
db.define_field_index("by_customer_id", ("customer_id",))
```

Query with an expression:

```python
from trellisdb import TrellisDB
from trellisdb.query.ast import Field

db = TrellisDB.open("./mydb.json", mode="r")
rows = db.find(prefix=("orders",), where=Field(("customer_id",), "==", "c2"))
```

---

## Running the FastAPI wrapper (optional)

After installing the server extras:

```bash
pip install "trellisdb[server]"
```

Run the server:

```bash
python -m uvicorn trellisdb.server.app:app --reload
```

The server will start at:

```
http://localhost:8000
```

---

## API documentation

FastAPI automatically exposes interactive documentation:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### REST endpoints (thin wrapper)

The server is intentionally a minimal translation layer over the library:

- `GET /info?path=...`
- `POST /init?path=...&dimensions=...&overwrite=false`
- `POST /item?path=...` (body: `{ "coords": [...], "value": ... }`)
- `GET /item?path=...&coords=...&coords=...`
- `DELETE /item?path=...` (body: `{ "coords": [...] }`)
- `GET /list?path=...&prefix=...&depth=...`
- `GET /find?path=...&prefix=...&field=...&op===&value=...&limit=...`

`/find` reads `value` as JSON when it parses, so `value=10` matches the number 10, `value=true` a boolean and `value=null` a null; anything that is not valid JSON, such as `value=c1`, is matched as a plain string. To match a string that looks like a number or a keyword, quote it: `value="10"` matches the string `"10"`.

The wrapper does not bypass durability or locking: it opens the database in `mode="r"` or `mode="rw"` as needed and uses the same commit semantics.

---

## Concurrency model (locking)

By default (`lock=True`), TrellisDB uses two lock files next to the database file:

- `*.writer.lock`: exclusive lock held for the lifetime of a writer session (`mode="rw"`)
- `*.rw.lock`: shared during reads; exclusive during `commit()`

This supports **single-writer / multiple-reader** access across processes.

---

## Versioning and compatibility

This project follows **semantic versioning**.

Guaranteed stable within a major version:

- Public `TrellisDB` API: `open`, `create`, `get`, `set`, `delete`, `exists`, `list`, `slice`, `find`, `commit`, `rollback`
- Public exception types in `trellisdb.errors`
- On-disk file format (`format=trellisdb`, `format_version=2`); files written under the project's earlier name still open and are rewritten in this format on their next commit

May change in minor versions:

- Internal module structure and private attributes
- Index query planning details

Breaking changes will only occur in the next major version.

---

## Development

Run tests:

```bash
python -m pytest -q
```

- [DEVELOPMENT.md](DEVELOPMENT.md): working from source, versioning and cutting a release.
- [TESTING.md](TESTING.md): the checks, what the suite covers and leaves out; how a test is written.
- [ARCHITECTURE.md](ARCHITECTURE.md): the storage format, durability, locking, indexing and the query system.

---

## Supporting the project

TrellisDB is free and stays free. There is no paid tier, no licence key and no feature held back behind a donation. If it has saved you time or simply been useful, a donation supports its maintenance and continued development.

<a href="https://www.paypal.com/ncp/payment/W6KW78BVJX2AS"><img src="https://ernster.dev/assets/donate.png" alt="Donate to TrellisDB" width="120"></a>

---

## Licence

MIT. See [LICENSE](LICENSE).

TrellisDB moved from GPL-3.0 to MIT after 1.0.6, a deliberate choice for adoption. A library is only useful to the teams that are allowed to import it; a GPL library is off limits to most commercial Python codebases. Its dependencies (portalocker, plus fastapi and uvicorn behind the `server` extra) are all under permissive licences, so nothing it pulls in contradicts the change. Releases up to and including 1.0.6 remain under GPL-3.0.
