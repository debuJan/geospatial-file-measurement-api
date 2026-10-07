# Geospatial File Measurement API

A production-style FastAPI backend that accepts geospatial file uploads
(zipped shapefiles or KML), extracts their features, and returns
area/length measurements computed in an appropriate projected CRS.

Built by **Debanshu Devgoswami** — https://github.com/debuJan

## Features

- `POST /api/files/` — upload a `.zip` (shapefile) or `.kml` file
- `GET /api/files/` — list all uploaded files
- `GET /api/files/{id}/` — file metadata: id, filename, feature count, CRS, status
- `GET /api/files/{id}/measurements/` — per-feature measurements
- Polygon/MultiPolygon → area in m², LineString/MultiLineString → length in m,
  Point/MultiPoint → `null` (graceful, never an error)
- Geographic CRSs (e.g. EPSG:4326) are reprojected to a UTM zone picked from
  the dataset centroid before any measurement — never computed on raw degrees
- SQLite persistence via SQLAlchemy; clean, typed, tested codebase

## Setup

Requirements: Python 3.10+.

```bash
git clone <your-repo-url>
cd geospatial-file-measurement-api

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

uvicorn app.main:app --reload
```

The API is then available at `http://127.0.0.1:8000`.
Interactive docs (Swagger UI): `http://127.0.0.1:8000/docs`.

Configuration via environment variables (all optional):

| Variable | Default | Description |
|---|---|---|
| `GEOAPI_DATABASE_URL` | `sqlite:///./geospatial.db` | SQLAlchemy database URL |
| `GEOAPI_UPLOAD_DIR` | `./uploads` | Where uploaded files are stored |
| `GEOAPI_MAX_UPLOAD_MB` | `50` | Max upload size in MB (413 beyond) |

## API

### Upload a file

```bash
curl -X POST http://127.0.0.1:8000/api/files/ \
  -F "file=@samples/sample.kml"
```

```bash
curl -X POST http://127.0.0.1:8000/api/files/ \
  -F "file=@samples/sample_shapefile.zip"
```

Response `201 Created`:

```json
{
  "id": "82d44ee7d2904af9bb6b845b4c1bce35",
  "filename": "sample.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED"
}
```

### File information

```bash
curl http://127.0.0.1:8000/api/files/82d44ee7d2904af9bb6b845b4c1bce35/
```

```json
{
  "id": "82d44ee7d2904af9bb6b845b4c1bce35",
  "filename": "sample.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "measurement_crs": "EPSG:32631",
  "created_at": "2026-10-07T14:41:57.192735"
}
```

### Measurements

```bash
curl http://127.0.0.1:8000/api/files/82d44ee7d2904af9bb6b845b4c1bce35/measurements/
```

```json
{
  "file_id": "82d44ee7d2904af9bb6b845b4c1bce35",
  "measurement_crs": "EPSG:32631",
  "measurements": [
    {
      "feature_index": 0,
      "geometry_type": "Polygon",
      "crs": "EPSG:4326",
      "properties": { "Name": "square", "Description": "..." },
      "measurement": { "type": "area", "value": 1233312.23, "unit": "sq_m" }
    },
    {
      "feature_index": 1,
      "geometry_type": "LineString",
      "crs": "EPSG:4326",
      "properties": { "Name": "line" },
      "measurement": { "type": "length", "value": 1114.28, "unit": "m" }
    },
    {
      "feature_index": 2,
      "geometry_type": "Point",
      "crs": "EPSG:4326",
      "properties": { "Name": "point" },
      "measurement": null
    }
  ]
}
```

### Error responses

| Situation | Status | Example |
|---|---|---|
| Wrong extension (e.g. `.txt`) | `400` | `{"detail": "Unsupported file type '.txt'..."}` |
| Empty zip / zip without `.shp` / not a zip | `400` | `{"detail": "No .shp file found inside the zip archive..."}` |
| Upload larger than the limit | `413` | `{"detail": "File too large..."}` |
| Malformed KML / broken shapefile | `422` | `{"detail": "Could not parse the KML file..."}` |
| Unknown file id | `404` | `{"detail": "No file found with id '...'"}` |

Error bodies never contain tracebacks.

## Architecture

### Project structure

```
geospatial-file-measurement-api/
├── app/
│   ├── main.py              # FastAPI app factory (create_app)
│   ├── config.py            # env-based settings
│   ├── db.py                # SQLite engine, sessions, init_db, get_db
│   ├── models.py            # SQLAlchemy models: GeoFile, Feature
│   ├── schemas.py           # Pydantic v2 request/response schemas
│   ├── api/
│   │   └── routes.py        # HTTP layer: validation, status codes, mapping
│   └── services/
│       ├── processing.py    # file parsing -> normalized features
│       ├── measurements.py  # area/length on projected geometries
│       └── crs.py           # CRS strategy: UTM-from-centroid
├── tests/                   # pytest suite (14 tests)
├── samples/                 # sample.kml + sample_shapefile.zip for quick trials
└── scripts/
    └── make_sample_shapefile.py  # regenerates the sample shapefile zip
```

### File-processing flow

```
client --multipart--> POST /api/files/
        1. extension check (.zip/.kml)            -> 400 otherwise
        2. size check (<= GEOAPI_MAX_UPLOAD_MB)   -> 413 otherwise
        3. persist bytes to uploads/<uuid>.<ext>, create DB row (PROCESSING)
        4. parse:
             .zip -> validate zip (400 on empty / no .shp / bad zip)
                   -> extract to temp dir -> read .shp with geopandas
             .kml -> read with pyogrio GDAL "KML" driver
             parse failures -> FileProcessingError -> 422, row marked FAILED
        5. normalise each feature: index, geometry type, geometry as GeoJSON
           (native CRS), CRS label, properties (JSON-safe attributes)
        6. pick measurement CRS from dataset centroid, reproject a working
           copy, measure, store rows
        7. row -> COMPLETED; return 201 with file metadata
```

### Measurement flow

`services/measurements.py` operates **only** on already-projected geometries:

- `Polygon` / `MultiPolygon` → `{"type": "area", "value", "unit": "sq_m"}`
- `LineString` / `MultiLineString` → `{"type": "length", "value", "unit": "m"}`
- `Point` / `MultiPoint`, empty geometries, `GeometryCollection`, or anything
  unknown → `None` (graceful, never raises)

### CRS handling

`services/crs.py` implements the core rule: **never measure on degrees.**

1. Read the file's native CRS (`EPSG:4326` assumed when missing — the KML spec
   defines KML as WGS84, and it's the conventional fallback for `.prj`-less
   shapefiles).
2. If the native CRS is already projected, use it directly.
3. If it is geographic, compute the centroid of all geometries (reprojecting
   the centroid to lon/lat first if needed) and select its UTM zone:
   `EPSG:326xx` (north) / `EPSG:327xx` (south).
4. Fallback to `EPSG:3857` when the centroid is missing/non-finite or polar
   (UTM is undefined beyond 84°N / 80°S).
5. One projected CRS is chosen per file (not per feature) so all measurements
   in a response are mutually consistent; it is reported as `measurement_crs`.

## Design decisions (and alternatives considered)

- **FastAPI over Django/DRF** — the service is a small, I/O-light API with no
  need for Django's ORM/admin/auth stack; FastAPI gives automatic OpenAPI
  docs, Pydantic v2 validation, and async upload handling with far less
  boilerplate.
- **SQLite via SQLAlchemy** — zero-ops persistence that survives restarts;
  the data model (files + features) is simple and the access pattern is
  write-once/read-many. Alternative: PostgreSQL + PostGIS for true spatial
  indexing and `ST_Area` in the database — the right call if this ever needs
  spatial queries at scale (see Future scope).
- **KML read via pyogrio's GDAL "KML" driver, not Fiona** — Fiona's
  prebuilt wheels are compiled without the LIBKML driver, so Fiona cannot
  open KML in this environment at all. pyogrio ships its own GDAL with KML
  support; it is the same GDAL machinery, just reachable.
- **UTM-from-centroid for the measurement CRS** — UTM zones are conformal
  with minimal distortion near the central meridian, making them the standard
  choice for accurate local area/length. Alternatives considered: always
  `EPSG:3857` (simple but increasingly distorted away from the equator),
  per-feature UTM zones (more accurate for continent-spanning files, but
  inconsistent within one response), and geodesic math via
  `pyproj.Geod` (no projection needed at all — a strong alternative; UTM was
  chosen because projected planar math is simpler to audit and matches the
  assignment's "transform to a projected CRS" requirement).
- **Synchronous processing in the request** — keeps the architecture simple
  and the assignment's flows easy to follow. For large files this should move
  to a background worker (Celery/RQ) with `PROCESSING` polling — noted below.
- **Metre assumption for already-projected CRSs** — if a file arrives in a
  projected CRS, it is used as-is. This assumes metre axis units (true for
  UTM, Web Mercator, national grids); a feet-based CRS would silently produce
  wrong units — documented as a limitation to fix (see Future scope).

## Testing

```bash
pytest -q
```

14 tests cover: KML upload, shapefile-zip upload, file-info endpoint,
area/length correctness on known equatorial geometries, UTM CRS selection,
point-measurement `null` handling, 400s (bad extension, empty zip,
zip-without-shp), 413 (oversize), 422 (malformed KML), 404s, and the list
endpoint.

## Learning

- GDAL driver availability is environment-dependent: the same library
  (Fiona) can read KML on one machine and not another depending on how its
  wheels were compiled — always verify with the actual runtime, and have a
  fallback driver.
- The single most error-prone part of geospatial work is CRS handling:
  measuring on unprojected degrees silently returns nonsense, so the
  "project first, measure second" ordering is enforced structurally (the
  measurement module only ever receives projected geometries).
- KML is always EPSG:4326 by spec, which removes a whole class of CRS
  ambiguity for that input type.

## Future scope

- Background processing (Celery/RQ) for large uploads with progress polling
- PostGIS backend with spatial indexing and in-database `ST_Area`/`ST_Length`
- Unit-aware handling of non-metre projected CRSs (read axis units via pyproj)
- Per-feature UTM zones or geodesic (`pyproj.Geod`) measurements for
  continent-spanning datasets
- Support for GeoJSON / GeoPackage / GPX inputs and `GeometryCollection`
  part-wise measurements
- File-level summary stats (total area, bounding box) and GeoJSON download
  of reprojected features
