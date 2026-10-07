"""Application entrypoint: FastAPI app factory."""
from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import router
from app.db import init_db


def create_app() -> FastAPI:
    app = FastAPI(
        title="Geospatial File Measurement API",
        version="1.0.0",
        description=(
            "Upload geospatial files (zipped shapefiles or KML), extract "
            "their features, and get area/length measurements computed in an "
            "appropriate projected CRS."
        ),
    )
    init_db()
    app.include_router(router, prefix="/api")

    @app.get("/health", tags=["health"], summary="Health check")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
