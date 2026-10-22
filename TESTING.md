# Testing

How TrellisDB is tested: running the checks, reading what they say, what the suite
covers and what it leaves out; how a new test is written. How the library
is built is in [ARCHITECTURE.md](ARCHITECTURE.md); setting up the environment
the tests run in is in [DEVELOPMENT.md](DEVELOPMENT.md).

## Running the checks

From the repository root, with the venv active:

```powershell
python -m pytest -q
python -m black --check .
python -m ruff check .
```

There is no CI, so nothing runs these for you; run all three and read the exit
code of each. ruff is configured in `pyproject.toml` with a wider rule set than
its defaults (pycodestyle, pyflakes, import order, pyupgrade, bugbear and
simplify).

**A full run takes a few seconds.** Measured on 2026-10-22: 77 tests passed
in about 4 seconds on Windows, with no expected failures (xfail) left.

**Read the exit code.** `0` means every test passed. There is no coverage gate
here, so the summary line is the result; `$LASTEXITCODE` is still the thing to
trust in a script.

## What the suite holds and leaves out

Testing emphasises real file IO and real multiprocess behaviour rather than
stand-ins: every test that touches storage writes a real database file into
pytest's `tmp_path`; the locking tests run real separate processes against
one file.

- **No coverage measurement.** pytest-cov is neither installed nor configured,
  so there is no floor and no figure.
- **The FastAPI wrapper is tested in process.** `TestClient` drives every
  endpoint against a real file; contention there comes from a writer held
  open in the test itself rather than from a second process.

## Where the tests live

All eleven files sit flat in `tests/`:

| File | What it holds |
|---|---|
| `test_storage_recovery.py` | recovery on open: which of the main file and a commit's temporary file is kept when they disagree; a refusal when neither is valid |
| `test_format_name.py` | new files carry the current format name; a file under the earlier format name opens and is rewritten on commit; an unknown name is refused |
| `test_locking_multiprocess.py` | across real processes, two writers cannot open together while a reader can open beside a writer that is confirmed to hold its session |
| `test_create_locking.py` | a `create(..., overwrite=True)` refused because another writer holds the file, in the same process and across real processes, leaves the old data intact |
| `test_failed_open_lock.py` | a writer open that fails on a corrupt or missing file releases the writer lock before it raises, so a second open reports the real cause |
| `test_api_basic.py` | the public operations: create, set, get, commit, rollback, read-only refusal, input validation, `list` and `find` |
| `test_find_indexed.py` | `find` using a field index for a simple equality, falling back when none matches |
| `test_slice.py` | `slice` with exact matches, wildcards and membership selectors |
| `test_keycodec.py` | the encoding of N-dimensional keys, pure |
| `test_server.py` | the FastAPI wrapper's `/init`, `/info` and `/item` endpoints over HTTP, including the 400, 404, 423 and 500 responses; the error translator called directly |
| `test_server_query.py` | the wrapper's `/list` and `/find` endpoints: prefix, depth, field predicates and limit, all sent in the query string; `value` decoded as JSON or kept as a string |

## Writing a test

- **Real files, not fakes.** Open the database on a path under `tmp_path`;
  durability and locking are what this library is for. A stand-in for the
  file would test the stand-in.
- **No mocking library.** None is used anywhere in the suite.
- **More than one process.** Follow `test_locking_multiprocess.py`: start real
  processes against the same file rather than simulating contention in one.

---

See also [README.md](README.md), [ARCHITECTURE.md](ARCHITECTURE.md) and
[DEVELOPMENT.md](DEVELOPMENT.md).
