"""SQLAlchemy ORM models.

Two tables:
  geo_files -- one row per uploaded file (metadata + processing status).
  features  -- one row per extracted feature, with geometry stored as GeoJSON
               text, attributes as JSON text, and the measurement as JSON text.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GeoFile(Base):
    __tablename__ = "geo_files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # uuid4 hex
    filename: Mapped[str] = mapped_column(String(255))
    extension: Mapped[str] = mapped_column(String(16))
    crs: Mapped[str] = mapped_column(String(64), default="")
    measurement_crs: Mapped[str] = mapped_column(String(64), default="")
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    # PROCESSING -> COMPLETED | FAILED
    status: Mapped[str] = mapped_column(String(16), default="PROCESSING")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    features: Mapped[list["Feature"]] = relationship(
        back_populates="geo_file", cascade="all, delete-orphan"
    )


class Feature(Base):
    __tablename__ = "features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(
        ForeignKey("geo_files.id", ondelete="CASCADE"), index=True
    )
    feature_index: Mapped[int] = mapped_column(Integer)
    geometry_type: Mapped[str] = mapped_column(String(32))
    crs: Mapped[str] = mapped_column(String(64), default="")
    geometry_geojson: Mapped[str] = mapped_column(Text)
    properties_json: Mapped[str] = mapped_column(Text, default="{}")
    # JSON like {"type": "area", "value": 123.4, "unit": "sq_m"} or NULL when
    # the geometry type has no measurement (e.g. Point).
    measurement_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    geo_file: Mapped["GeoFile"] = relationship(back_populates="features")
