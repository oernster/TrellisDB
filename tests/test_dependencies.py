from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
LOCK_PACKAGE = "portalocker"
# portalocker 4.0.0 moved pywin32, which a shared lock on Windows needs, behind
# this extra; without it a fresh install cannot create a database there.
WINDOWS_LOCK_EXTRA = "win32"


def _lock_requirements(sys_platform: str) -> list[Requirement]:
    deps = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    reqs = [Requirement(d) for d in deps["dependencies"]]
    return [
        r
        for r in reqs
        if r.name == LOCK_PACKAGE
        and (r.marker is None or r.marker.evaluate({"sys_platform": sys_platform}))
    ]


def test_windows_install_pulls_in_the_shared_lock_extra() -> None:
    reqs = _lock_requirements("win32")

    assert reqs
    assert all(WINDOWS_LOCK_EXTRA in r.extras for r in reqs)


@pytest.mark.parametrize("sys_platform", ["linux", "darwin"])
def test_other_platforms_still_depend_on_the_lock_package(sys_platform: str) -> None:
    assert _lock_requirements(sys_platform)
