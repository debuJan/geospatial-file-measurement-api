"""File parsing: KML and zipped Shapefile -> normalized feature records.

Responsibilities:
  * Read the uploaded file into a GeoDataFrame (KML via pyogrio's GDAL "KML"
    driver -- the Fiona wheels in this environment lack LIBKML support;
    zipped shapefiles via geopandas).
  * Validate structure (non-empty zip, a .shp present, parseable content).
  * Normalise every feature to: index, geometry type, geometry (GeoJSON in the
    file's native CRS), CRS, and properties/attributes.
  * Choose the measurement CRS (see app.services.crs), reproject a copy of
    each geometry, and attach the measurement.

Two error types separate client-caused problems from server bugs:
  * InvalidUploadError   -> HTTP 400 (the upload itself is structurally wrong)
  * FileProcessingError  -> HTTP 422 (the content is malformed/unparseable)
"""
from __future__ import annotations

import io
import json
import math
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
from pyproj import CRS
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from app.services.crs import (
    crs_to_string,
    measurement_crs,
    representative_lonlat,
)
from app.services.measurements import measure_geometry


class InvalidUploadError(Exception):
    """The uploaded file is structurally invalid (400)."""


class FileProcessingError(Exception):
    """The file content could not be parsed (422)."""


@dataclass
class ParsedFeature:
    index: int
    geometry_type: str
    crs: str
    geometry_geojson: dict[str, Any]
    properties: dict[str, Any]
    measurement: dict[str, Any] | None


@dataclass
class ParsedFile:
    crs: str  # native CRS of the uploaded file, e.g. "EPSG:4326"
    measurement_crs: str  # projected CRS measurements were computed in
    features: list[ParsedFeature] = field(default_factory=list)


def _json_safe(value: Any) -> Any:
    """Coerce attribute values to JSON-serialisable primitives.

    Handles numpy scalars, pandas NA/NaT, NaN floats, and datetimes. Falls
    back to str() so an exotic attribute value can never crash processing.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    try:
        import numpy as np  # local import: numpy ships with geopandas

        if isinstance(value, np.generic):
            return _json_safe(value.item())
    except ImportError:  # pragma: no cover
        pass
    try:
        import pandas as pd

        if pd.isna(value):
            return None
    except (ImportError, ValueError, TypeError):  # pragma: no cover
        pass
    return str(value)


def _read_kml(path: Path) -> gpd.GeoDataFrame:
    # NOTE: read via pyogrio's GDAL "KML" driver rather than Fiona: the Fiona
    # wheels available here are not built with the LIBKML driver, so Fiona
    # cannot open KML at all in this environment. pyogrio ships its own GDAL
    # with KML support ("KML" driver, rw). Same GDAL machinery either way.
    try:
        gdf = gpd.read_file(path, engine="pyogrio", driver="KML")
    except Exception as exc:
        raise FileProcessingError(
            f"Could not parse the KML file ({exc}). "
            "Make sure it is a valid KML document."
        ) from exc
    return gdf


def _read_shapefile_zip(path: Path) -> gpd.GeoDataFrame:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise InvalidUploadError(
            "The uploaded file is not a valid zip archive."
        ) from exc

    with archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
        if not names:
            raise InvalidUploadError("The zip archive is empty.")
        shp_names = [n for n in names if n.lower().endswith(".shp")]
        if not shp_names:
            raise InvalidUploadError(
                "No .shp file found inside the zip archive. "
                "Upload a zip containing a complete shapefile (.shp, .shx, .dbf)."
            )
        with tempfile.TemporaryDirectory() as tmpdir:
            archive.extractall(tmpdir)
            shp_path = Path(tmpdir) / shp_names[0]
            try:
                gdf = gpd.read_file(shp_path)
            except Exception as exc:
                raise FileProcessingError(
                    f"Could not parse the shapefile ({exc}). "
                    "Make sure the zip contains a valid .shp/.shx/.dbf set."
                ) from exc
    return gdf


def _native_crs(gdf: gpd.GeoDataFrame) -> CRS:
    """Native CRS of the file; KML/shapefiles without CRS default to EPSG:4326.

    KML is defined by the spec as WGS84 (EPSG:4326), and many shapefiles ship
    without a .prj -- EPSG:4326 is the conventional assumption. Documented in
    README under Design Decisions.
    """
    if gdf.crs is not None:
        return gdf.crs
    return CRS.from_epsg(4326)


def parse_upload(path: Path, extension: str) -> ParsedFile:
    """Parse an uploaded file into normalized features with measurements."""
    if extension == ".kml":
        gdf = _read_kml(path)
    elif extension == ".zip":
        gdf = _read_shapefile_zip(path)
    else:  # defensive; routes validate the extension first
        raise InvalidUploadError(f"Unsupported file extension '{extension}'.")

    source_crs = _native_crs(gdf)
    crs_str = crs_to_string(source_crs)

    # Drop rows without a geometry; keep the rest (even empty ones).
    geoms: list[BaseGeometry | None] = list(gdf.geometry)
    valid_idx = [i for i, g in enumerate(geoms) if g is not None]

    lon, lat = representative_lonlat([geoms[i] for i in valid_idx], source_crs)
    meas_crs = measurement_crs(source_crs, lon, lat)
    meas_crs_str = crs_to_string(meas_crs)

    # Reproject a working copy for measurement; stored geometry stays native.
    projected = gdf.geometry.to_crs(meas_crs) if valid_idx else gdf.geometry

    geom_col = gdf.geometry.name
    features: list[ParsedFeature] = []
    for out_index, i in enumerate(valid_idx):
        row = gdf.iloc[i]
        native_geom = geoms[i]
        proj_geom = projected.iloc[i]
        assert native_geom is not None
        properties = {
            col: _json_safe(row[col]) for col in gdf.columns if col != geom_col
        }
        features.append(
            ParsedFeature(
                index=out_index,
                geometry_type=native_geom.geom_type,
                crs=crs_str,
                geometry_geojson=mapping(native_geom),
                properties=properties,
                measurement=measure_geometry(proj_geom),
            )
        )

    return ParsedFile(crs=crs_str, measurement_crs=meas_crs_str, features=features)


def feature_to_storage(feature: ParsedFeature) -> dict[str, Any]:
    """Convert a ParsedFeature to DB-storable string fields."""
    return {
        "feature_index": feature.index,
        "geometry_type": feature.geometry_type,
        "crs": feature.crs,
        "geometry_geojson": json.dumps(feature.geometry_geojson),
        "properties_json": json.dumps(feature.properties),
        "measurement_json": (
            json.dumps(feature.measurement) if feature.measurement else None
        ),
    }
