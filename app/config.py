"""Application configuration.

All settings can be overridden with environment variables so the service can
be configured without code changes (12-factor style).
"""
from __future__ import annotations

import os


class Settings:
    """Settings holder.

    Deliberately a plain (mutable) class rather than a frozen dataclass so
    tests can monkeypatch individual values at runtime.
    """

    def __init__(self) -> None:
        self.DATABASE_URL: str = os.environ.get(
            "GEOAPI_DATABASE_URL", "sqlite:///./geospatial.db"
        )
        self.UPLOAD_DIR: str = os.environ.get("GEOAPI_UPLOAD_DIR", "./uploads")
        # Maximum accepted upload size; larger uploads are rejected with 413.
        self.MAX_UPLOAD_BYTES: int = (
            int(os.environ.get("GEOAPI_MAX_UPLOAD_MB", "50")) * 1024 * 1024
        )


settings = Settings()
