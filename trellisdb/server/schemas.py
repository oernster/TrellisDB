"""Pydantic request/response schemas for the FastAPI wrapper."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class InitResponse(BaseModel):
    path: str
    dimensions: int
    created: bool


class ItemBody(BaseModel):
    coords: list[str] = Field(..., description="N-dimensional coordinate key")
    value: Any


class DeleteBody(BaseModel):
    coords: list[str]
