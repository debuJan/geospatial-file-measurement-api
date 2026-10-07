"""API tests for the Geospatial File Measurement API."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, Polygon

from app.config import settings

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"

# A 0.01 x 0.01 degree square sitting on the equator.
# Expected area ~= 0.01deg_lon * 0.01deg_lat ~= 1113.2m * 1105.7m ~= 1.23e6 m^2
# Expected length of the 0.01-degree equatorial line ~= 1113 m.
SQUARE = Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01)])
TRIANGLE = Polygon([(0.02, 0), (0.03, 0), (0.025, 0.01)])
LINE = LineString([(0, 0), (0.01, 0)])
POINT = Point(0.005, 0.005)


def sample_kml_bytes() -> bytes:
    return (SAMPLES_DIR / "sample.kml").read_bytes()


def shapefile_zip_bytes(tmp_path: Path) -> bytes:
    """Build a small polygon-only shapefile zip in memory (EPSG:4326)."""
    gdf = gpd.GeoDataFrame(
        {"name": ["square", "triangle"], "value": [1, 2]},
        geometry=[SQUARE, TRIANGLE],
        crs="EPSG:4326",
    )
    shp_dir = tmp_path / "shp"
    shp_dir.mkdir()
    gdf.to_file(shp_dir / "sample.shp")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for part in sorted(shp_dir.iterdir()):
            z.write(part, part.name)
    return buf.getvalue()


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def upload(client, filename: str, content: bytes, content_type: str):
    return client.post(
        "/api/files/", files={"file": (filename, content, content_type)}
    )


def by_geom_type(measurements, geom_type):
    return [m for m in measurements if m["geometry_type"] == geom_type]


# --- happy paths -----------------------------------------------------------

def test_upload_kml_returns_201_and_metadata(client):
    resp = upload(client, "sample.kml", sample_kml_bytes(),
                  "application/vnd.google-earth.kml+xml")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["filename"] == "sample.kml"
    assert body["feature_count"] == 3
    assert body["crs"] == "EPSG:4326"
    assert body["status"] == "COMPLETED"
    assert len(body["id"]) == 32


def test_get_file_info(client):
    file_id = upload(client, "sample.kml", sample_kml_bytes(), "text/xml").json()["id"]
    resp = client.get(f"/api/files/{file_id}/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == file_id
    assert body["filename"] == "sample.kml"
    assert body["feature_count"] == 3
    assert body["crs"] == "EPSG:4326"
    assert body["status"] == "COMPLETED"


def test_upload_shapefile_zip(client, tmp_path):
    resp = upload(client, "sample.zip", shapefile_zip_bytes(tmp_path),
                  "application/zip")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["feature_count"] == 2
    assert body["crs"] == "EPSG:4326"
    assert body["status"] == "COMPLETED"


def test_measurements_polygon_area_is_sane(client):
    file_id = upload(client, "sample.kml", sample_kml_bytes(), "text/xml").json()["id"]
    resp = client.get(f"/api/files/{file_id}/measurements/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["file_id"] == file_id
    # UTM zone 31N for lon ~0: sanity check the CRS strategy kicked in.
    assert body["measurement_crs"] == "EPSG:32631"
    polys = by_geom_type(body["measurements"], "Polygon")
    assert len(polys) == 1
    m = polys[0]["measurement"]
    assert m["type"] == "area" and m["unit"] == "sq_m"
    assert 1_200_000 < m["value"] < 1_260_000  # ~1.23e6 m^2 expected


def test_measurements_linestring_length_is_sane(client):
    file_id = upload(client, "sample.kml", sample_kml_bytes(), "text/xml").json()["id"]
    resp = client.get(f"/api/files/{file_id}/measurements/")
    assert resp.status_code == 200, resp.text
    lines = by_geom_type(resp.json()["measurements"], "LineString")
    assert len(lines) == 1
    m = lines[0]["measurement"]
    assert m["type"] == "length" and m["unit"] == "m"
    assert 1_100 < m["value"] < 1_130  # ~1113 m expected


def test_measurements_point_is_null_but_graceful(client):
    file_id = upload(client, "sample.kml", sample_kml_bytes(), "text/xml").json()["id"]
    resp = client.get(f"/api/files/{file_id}/measurements/")
    assert resp.status_code == 200, resp.text
    points = by_geom_type(resp.json()["measurements"], "Point")
    assert len(points) == 1
    assert points[0]["measurement"] is None  # graceful, not an error


def test_measurements_shapefile_polygons(client, tmp_path):
    file_id = upload(
        client, "sample.zip", shapefile_zip_bytes(tmp_path), "application/zip"
    ).json()["id"]
    resp = client.get(f"/api/files/{file_id}/measurements/")
    assert resp.status_code == 200, resp.text
    measurements = resp.json()["measurements"]
    assert len(measurements) == 2
    areas = sorted(m["measurement"]["value"] for m in measurements)
    assert 1_200_000 < areas[1] < 1_260_000  # square
    assert 600_000 < areas[0] < 630_000  # triangle ~615k m^2
    # properties/attributes are preserved
    names = sorted(m["properties"]["name"] for m in measurements)
    assert names == ["square", "triangle"]


def test_list_files(client, tmp_path):
    upload(client, "a.kml", sample_kml_bytes(), "text/xml")
    upload(client, "b.zip", shapefile_zip_bytes(tmp_path), "application/zip")
    resp = client.get("/api/files/")
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 2


# --- validation / error paths ----------------------------------------------

def test_unsupported_extension_rejected_with_400(client):
    resp = upload(client, "notes.txt", b"hello world", "text/plain")
    assert resp.status_code == 400
    assert "Unsupported file type" in resp.json()["detail"]


def test_empty_zip_rejected_with_400(client):
    resp = upload(client, "empty.zip", zip_bytes({}), "application/zip")
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()


def test_zip_without_shapefile_rejected_with_400(client):
    resp = upload(
        client, "noshp.zip", zip_bytes({"readme.txt": b"no shapes here"}),
        "application/zip",
    )
    assert resp.status_code == 400
    assert ".shp" in resp.json()["detail"]


def test_malformed_kml_rejected_with_422(client):
    resp = upload(client, "broken.kml", b"<kml><this is not valid", "text/xml")
    assert resp.status_code == 422
    assert resp.json()["detail"]  # clear message, no traceback


def test_unknown_file_id_returns_404(client):
    assert client.get("/api/files/doesnotexist/").status_code == 404
    assert client.get("/api/files/doesnotexist/measurements/").status_code == 404


def test_oversize_upload_rejected_with_413(client, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 10)
    resp = upload(client, "sample.kml", sample_kml_bytes(), "text/xml")
    assert resp.status_code == 413
