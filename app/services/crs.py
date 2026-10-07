"""CRS utilities.

Core rule: never compute area/length directly on geographic (lat/lon degree)
coordinates. Measurements are always computed in a projected CRS.

Strategy for picking the projected CRS (documented in README):
  * Source CRS is already projected  -> use it as-is. (Assumption: its axis
    unit is metres; non-metre projected CRSs are a documented limitation.)
  * Source CRS is geographic          -> use the UTM zone of the dataset's
    representative point (centroid of all geometries, reprojected to lon/lat
    when needed): EPSG:326xx in the northern hemisphere, EPSG:327xx in the
    southern hemisphere.
  * Fallback                          -> EPSG:3857 (Web Mercator) when the
    representative point is missing, non-finite, or polar (UTM is undefined
    beyond 84N / 80S).
"""
from __future__ import annotations

import math

from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry


def is_geographic(crs: CRS) -> bool:
    return crs.is_geographic


def utm_epsg_for_lonlat(lon: float, lat: float) -> int:
    """Return the UTM EPSG code for a lon/lat point, EPSG:3857 on fallback."""
    if not (math.isfinite(lon) and math.isfinite(lat)):
        return 3857
    if abs(lat) >= 84:  # UTM is undefined in polar regions
        return 3857
    lon = ((lon + 180) % 360) - 180  # normalise to [-180, 180)
    zone = int((lon + 180) // 6) + 1
    zone = min(max(zone, 1), 60)
    return (32600 if lat >= 0 else 32700) + zone


def representative_lonlat(
    geometries: list[BaseGeometry], source_crs: CRS
) -> tuple[float, float]:
    """Lon/lat of the centroid of all geometries (for UTM zone selection)."""
    valid = [g for g in geometries if g is not None and not g.is_empty]
    if not valid:
        return (0.0, 0.0)  # no geometries; the choice is moot, fallback applies
    # Union then centroid is a stable representative point for the dataset.
    union = valid[0]
    for g in valid[1:]:
        union = union.union(g)
    centroid = union.centroid
    if source_crs.is_geographic:
        return (float(centroid.x), float(centroid.y))
    transformer = Transformer.from_crs(source_crs, CRS.from_epsg(4326), always_xy=True)
    lon, lat = transformer.transform(centroid.x, centroid.y)
    return (float(lon), float(lat))


def measurement_crs(source_crs: CRS, lon: float, lat: float) -> CRS:
    """Pick the projected CRS in which measurements should be computed."""
    if source_crs.is_projected:
        return source_crs
    return CRS.from_epsg(utm_epsg_for_lonlat(lon, lat))


def crs_to_string(crs: CRS) -> str:
    """Human-friendly CRS label, e.g. 'EPSG:4326'."""
    epsg = crs.to_epsg()
    if epsg is not None:
        return f"EPSG:{epsg}"
    return crs.to_string()
