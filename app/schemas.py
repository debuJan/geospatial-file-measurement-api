"""Pydantic v2 response schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class FileSummary(BaseModel):
    id: str
    filename: str
    feature_count: int
    crs: str
    status: str


class FileInfoResponse(FileSummary):
    """GET /api/files/{id}/ -- mirrors the spec's example payload."""

    measurement_crs: str
    created_at: datetime


class FileListItem(FileSummary):
    created_at: datetime


class Measurement(BaseModel):
    type: str = Field(description="'area' for polygons, 'length' for lines")
    value: float
    unit: str = Field(description="'sq_m' for area, 'm' for length")


class FeatureMeasurement(BaseModel):
    feature_index: int
    geometry_type: str
    crs: str
    properties: dict[str, Any]
    # None for geometry types with no measurement (Point/MultiPoint,
    # empty or otherwise unmeasurable geometries) -- never an error.
    measurement: Optional[Measurement] = None


class MeasurementsResponse(BaseModel):
    file_id: str
    measurement_crs: str
    measurements: list[FeatureMeasurement]


class ErrorResponse(BaseModel):
    detail: str
