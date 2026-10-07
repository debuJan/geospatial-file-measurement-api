"""Measurement calculations.

All functions here expect geometries that are ALREADY in a projected,
metre-based CRS (see app.services.crs). They never see lat/lon degrees.
"""
from __future__ import annotations

from typing import Any, Optional

from shapely.geometry.base import BaseGeometry

AREA_TYPES = {"Polygon", "MultiPolygon"}
LENGTH_TYPES = {"LineString", "MultiLineString"}
POINT_TYPES = {"Point", "MultiPoint"}


def measure_geometry(geom: BaseGeometry | None) -> Optional[dict[str, Any]]:
    """Measure a projected geometry.

    Returns:
        {"type": "area", "value": <float>, "unit": "sq_m"} for polygons,
        {"type": "length", "value": <float>, "unit": "m"} for lines,
        None for points, empty geometries, GeometryCollections, or any
        other/unknown geometry type.

    Never raises: unsupported or degenerate input degrades to None so the API
    stays graceful instead of crashing (per the assignment spec).
    """
    try:
        if geom is None or geom.is_empty:
            return None
        geom_type = geom.geom_type
        if geom_type in AREA_TYPES:
            return {"type": "area", "value": float(geom.area), "unit": "sq_m"}
        if geom_type in LENGTH_TYPES:
            return {"type": "length", "value": float(geom.length), "unit": "m"}
        # Points carry no measurement; collections/unknown types are returned
        # as None rather than raising.
        return None
    except Exception:
        return None
