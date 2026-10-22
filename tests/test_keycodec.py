from __future__ import annotations

import pytest

from trellisdb.engine.keycodec import decode_key, encode_key
from trellisdb.errors import ValidationError


@pytest.mark.parametrize(
    "components",
    [
        ("a",),
        ("a", "b"),
        ("user1", "2025-01", "orders"),
        ("with space", "with/slash", "with%percent"),
        ("", "empty", "component"),
    ],
)
def test_encode_decode_roundtrip(components: tuple[str, ...]) -> None:
    assert decode_key(encode_key(components)) == components


def test_decode_empty_string_is_empty_tuple() -> None:
    assert decode_key("") == ()


def test_encode_rejects_non_string_component() -> None:
    with pytest.raises(ValidationError):
        encode_key(("ok", 123))  # type: ignore[arg-type]
