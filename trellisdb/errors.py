"""Public error types for TrellisDB."""

from __future__ import annotations


class TrellisDBError(Exception):
    """Base class for all TrellisDB errors."""


class StorageCorruptionError(TrellisDBError):
    """Raised when on-disk data is missing or cannot be validated/recovered."""


class LockError(TrellisDBError):
    """Raised when the database cannot acquire the required file locks."""


class ReadOnlyError(TrellisDBError):
    """Raised when attempting to mutate state in read-only mode."""


class ValidationError(TrellisDBError, ValueError):
    """Raised when inputs fail validation (keys, values, schema)."""


class InvalidCoordsError(ValidationError):
    """Raised when a key/coords value is not a valid coordinate sequence."""


class WrongDimensionLengthError(ValidationError):
    """Raised when a key has the wrong number of dimensions for this database."""


class NonJsonSerializableValueError(ValidationError):
    """Raised when a value cannot be JSON-serialized by the default serializer."""
