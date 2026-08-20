"""Pydantic response models for splice-api (the typed side of the boundary)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "splice-api"
    version: str


class CompareSummary(BaseModel):
    """JSON summary of a DTx compare — the counts the UIs show as metric tiles."""

    old_file: str
    new_file: str
    added_cnums: int = Field(ge=0)
    removed_cnums: int = Field(ge=0)
    added_circuits: int = Field(ge=0)
    removed_circuits: int = Field(ge=0)
    modified_circuits: int = Field(ge=0)
    harness_families: list[str]
    dtcr_total: int = Field(ge=0)
    dtcr_matched: int = Field(ge=0)
    output_file_name: str
