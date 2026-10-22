"""Prefix index.

This is a correctness-first implementation:

- The on-disk prefix index stores all encoded keys in sorted order.
- Prefix scans become a bisect range query.
"""

from __future__ import annotations

from bisect import bisect_left
from typing import Any


def rebuild_prefix_keys(data: dict[str, Any]) -> list[str]:
    return sorted(data.keys())


def select_prefix_range(prefix_keys: list[str], encoded_prefix: str) -> tuple[int, int]:
    """Return [lo, hi) range of keys starting with encoded_prefix.

    We approximate the end bound by choosing a lexicographic successor string.
    For ASCII-safe encodings this works well.

    Note: this is correct when keys are restricted to a stable encoding that
    does not introduce characters below the sentinel.
    """

    if encoded_prefix == "":
        return 0, len(prefix_keys)

    lo = bisect_left(prefix_keys, encoded_prefix)
    # '' is DEL, lexicographically higher than typical URL-escaped chars.
    hi = bisect_left(prefix_keys, encoded_prefix + "\u007f")
    return lo, hi
