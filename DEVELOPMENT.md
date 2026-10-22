# Development

How to work on TrellisDB from source and cut a release. What it is and how to use
it is in [README.md](README.md); how it is built is in
[ARCHITECTURE.md](ARCHITECTURE.md); running and writing the tests is in
[TESTING.md](TESTING.md). Commands run from the repository root.

## Tools

| Tool | What for | Where from |
|---|---|---|
| Python 3.11 or newer | everything | [python.org](https://www.python.org/downloads/) |
| portalocker | the library's one runtime dependency: the file locks; its `win32` extra adds pywin32 on Windows, which a shared lock there needs from portalocker 4.0.0 | `pyproject.toml`, installed with the package |
| fastapi, uvicorn | the optional HTTP wrapper | the `server` extra |
| pytest, black, ruff, httpx | the checks | `requirements.txt` |
| build, twine (or another uploader) | cutting a release | not in the repository; install them when releasing |

`requirements.txt` is the development environment, not the library's
requirements: it lists the checks, the server extra and portalocker together.
The library itself depends on portalocker alone (with pywin32 beside it on
Windows, through that extra).

## Running from source

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e .
```

The editable install puts `trellisdb` on the path exactly as a user's
`pip install trellisdb` would. To run the HTTP wrapper with its interactive API
documentation, see the README's section on the FastAPI wrapper.

A database here is a JSON file plus two lock files beside it
(`*.writer.lock` and `*.rw.lock`). `.gitignore` ignores every `*.json` file
anywhere in the repository, along with both lock patterns, so a scratch database
made while working never lands in a commit. It also means a JSON file meant to
be committed has to be added with `git add -f`.

## Versioning

The version is written in one place, `version` in `pyproject.toml`; PyPI is the
release surface, so there is no separate `VERSION` file. The project follows
semantic versioning; the README's Versioning section says what is held
stable within a major version: the public API, the public exception types and
the on-disk format.

## Cutting a release

1. Set `version` in `pyproject.toml`.
2. Run the checks in [TESTING.md](TESTING.md); all three must exit 0.
3. Build the two artefacts:

   ```powershell
   python -m pip install build
   python -m build
   ```

   which writes `dist/trellisdb-<version>.tar.gz` and
   `dist/trellisdb-<version>-py3-none-any.whl`. `dist/` is gitignored.
4. Upload both files to PyPI, for example with
   `python -m twine upload dist/*` after `python -m pip install twine`.
5. Tag the release `v` plus the version, as every release so far has been
   (`v1.1.0`, `v1.0.6` and before).

## Standing rules

- portalocker stays the only runtime dependency; anything else goes in an
  optional extra.
- The HTTP wrapper never bypasses durability or locking: it opens the library
  with the right mode for each endpoint rather than touching the file itself.
- A change to the on-disk format, the public API or the public exception types
  is a major version.

---

See also [README.md](README.md), [ARCHITECTURE.md](ARCHITECTURE.md) and
[TESTING.md](TESTING.md).
