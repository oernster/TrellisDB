"""Reversible encoding for N-dimensional coordinate keys.

Keys are represented externally as sequences of strings (components).
On disk we store a single encoded string using '/' separators.

We percent-encode each component with no safe characters to ensure
reversibility even when components contain '/', '%' or whitespace.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from urllib.parse import quote, unquote

from trellisdb.errors import ValidationError

_SEP = "/"


def encode_component(component: str) -> str:
    if not isinstance(component, str):
        raise ValidationError("Key components must be strings")
    # safe="" ensures '/' is always encoded.
    return quote(component, safe="")


def decode_component(encoded: str) -> str:
    if not isinstance(encoded, str):
        raise ValidationError("Encoded key components must be strings")
    return unquote(encoded)


def encode_key(components: Sequence[str]) -> str:
    if not isinstance(components, Sequence):
        raise ValidationError("Key must be a sequence of strings")
    return _SEP.join(encode_component(c) for c in components)


def decode_key(encoded_key: str) -> tuple[str, ...]:
    if not isinstance(encoded_key, str):
        raise ValidationError("Encoded key must be a string")
    if encoded_key == "":
        return ()
    return tuple(decode_component(part) for part in encoded_key.split(_SEP))


def encode_prefix(prefix: Iterable[str]) -> str:
    """Encode a prefix (0..N components) into an encoded key prefix."""

    return encode_key(tuple(prefix))
