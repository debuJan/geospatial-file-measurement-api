"""Generate samples/sample_shapefile.zip for manual testing / curl demos.

Run:  python scripts/make_sample_shapefile.py
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parent.parent
OUT_ZIP = ROOT / "samples" / "sample_shapefile.zip"


def main() -> None:
    square = Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01)])
    triangle = Polygon([(0.02, 0), (0.03, 0), (0.025, 0.01)])
    gdf = gpd.GeoDataFrame(
        {"name": ["square", "triangle"], "value": [1, 2]},
        geometry=[square, triangle],
        crs="EPSG:4326",
    )
    tmpdir = ROOT / "samples" / "_shp_tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    gdf.to_file(tmpdir / "sample.shp")
    OUT_ZIP.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for part in sorted(tmpdir.iterdir()):
            z.write(part, part.name)
    for part in tmpdir.iterdir():
        part.unlink()
    tmpdir.rmdir()
    print(f"Wrote {OUT_ZIP}")


if __name__ == "__main__":
    main()
