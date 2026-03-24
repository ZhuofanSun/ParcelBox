"""Pydantic models for Phase 3 control endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AccessWindowPayload(BaseModel):
    days: list[int] = Field(default_factory=list)
    start: str = "00:00"
    end: str = "23:59"


class CardEnrollPayload(BaseModel):
    uid: str | None = None
    name: str | None = None
    enabled: bool = True
    overwrite: bool = False
    access_windows: list[AccessWindowPayload] = Field(default_factory=list)
    scan_timeout_seconds: float | None = None


class CardUpdatePayload(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    access_windows: list[AccessWindowPayload] | None = None


class LockerActionPayload(BaseModel):
    source: str = "api"
