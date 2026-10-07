"""API routes for the Geospatial File Measurement API."""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.db import get_db
from app.schemas import (
    ErrorResponse,
    FeatureMeasurement,
    FileInfoResponse,
    FileListItem,
    FileSummary,
    Measurement,
    MeasurementsResponse,
)
from app.services.processing import (
    FileProcessingError,
    InvalidUploadError,
    feature_to_storage,
    parse_upload,
)

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_EXTENSIONS = {".zip", ".kml"}


def _summary(record: models.GeoFile) -> FileSummary:
    return FileSummary(
        id=record.id,
        filename=record.filename,
        feature_count=record.feature_count,
        crs=record.crs,
        status=record.status,
    )


@router.post(
    "/files/",
    response_model=FileSummary,
    status_code=201,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid upload"},
        413: {"model": ErrorResponse, "description": "Upload too large"},
        422: {"model": ErrorResponse, "description": "Unparseable content"},
    },
    summary="Upload a geospatial file",
    description=(
        "Accepts a `.zip` containing a shapefile or a `.kml` file, extracts "
        "its features, computes measurements, and stores everything. "
        "Returns the file's metadata including its processing status."
    ),
)
async def upload_file(
    file: UploadFile = File(..., description="A .zip (shapefile) or .kml file"),
    db: Session = Depends(get_db),
) -> FileSummary:
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{extension or '(none)'}'. "
                "Upload a .zip containing a shapefile or a .kml file."
            ),
        )

    data = await file.read()
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large ({len(data)} bytes). "
                f"Maximum allowed is {settings.MAX_UPLOAD_BYTES} bytes."
            ),
        )

    file_id = uuid.uuid4().hex
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_path = upload_dir / f"{file_id}{extension}"
    stored_path.write_bytes(data)

    record = models.GeoFile(
        id=file_id,
        filename=file.filename or f"upload{extension}",
        extension=extension,
        status="PROCESSING",
    )
    db.add(record)
    db.commit()

    try:
        parsed = parse_upload(stored_path, extension)
    except InvalidUploadError as exc:
        record.status = "FAILED"
        record.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc))
    except FileProcessingError as exc:
        record.status = "FAILED"
        record.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:  # never leak tracebacks to the client
        logger.exception("Unexpected error processing upload %s", file_id)
        record.status = "FAILED"
        record.error_message = "Internal error while processing the file."
        db.commit()
        raise HTTPException(
            status_code=500, detail="Internal error while processing the file."
        )

    for feature in parsed.features:
        db.add(models.Feature(file_id=file_id, **feature_to_storage(feature)))
    record.crs = parsed.crs
    record.measurement_crs = parsed.measurement_crs
    record.feature_count = len(parsed.features)
    record.status = "COMPLETED"
    db.commit()
    db.refresh(record)
    return _summary(record)


@router.get(
    "/files/",
    response_model=list[FileListItem],
    summary="List uploaded files",
)
def list_files(db: Session = Depends(get_db)) -> list[FileListItem]:
    records = (
        db.query(models.GeoFile).order_by(models.GeoFile.created_at.desc()).all()
    )
    return [
        FileListItem(
            **_summary(r).model_dump(),
            created_at=r.created_at,
        )
        for r in records
    ]


def _get_record_or_404(file_id: str, db: Session) -> models.GeoFile:
    record = db.query(models.GeoFile).filter(models.GeoFile.id == file_id).first()
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"No file found with id '{file_id}'."
        )
    return record


@router.get(
    "/files/{file_id}/",
    response_model=FileInfoResponse,
    responses={404: {"model": ErrorResponse, "description": "File not found"}},
    summary="Get file information",
)
def get_file_info(file_id: str, db: Session = Depends(get_db)) -> FileInfoResponse:
    record = _get_record_or_404(file_id, db)
    return FileInfoResponse(
        **_summary(record).model_dump(),
        measurement_crs=record.measurement_crs,
        created_at=record.created_at,
    )


@router.get(
    "/files/{file_id}/measurements/",
    response_model=MeasurementsResponse,
    responses={
        404: {"model": ErrorResponse, "description": "File not found"},
        422: {"model": ErrorResponse, "description": "File failed processing"},
    },
    summary="Get measurements for a file's features",
    description=(
        "Returns per-feature measurements. Polygons report area in square "
        "metres, lines report length in metres, and points (or any other "
        "unmeasurable geometry) report a null measurement -- never an error."
    ),
)
def get_measurements(
    file_id: str, db: Session = Depends(get_db)
) -> MeasurementsResponse:
    record = _get_record_or_404(file_id, db)
    if record.status == "FAILED":
        raise HTTPException(
            status_code=422,
            detail=f"File processing failed: {record.error_message or 'unknown error'}.",
        )
    features = (
        db.query(models.Feature)
        .filter(models.Feature.file_id == file_id)
        .order_by(models.Feature.feature_index)
        .all()
    )
    measurements = [
        FeatureMeasurement(
            feature_index=f.feature_index,
            geometry_type=f.geometry_type,
            crs=f.crs,
            properties=json.loads(f.properties_json or "{}"),
            measurement=(
                Measurement(**json.loads(f.measurement_json))
                if f.measurement_json
                else None
            ),
        )
        for f in features
    ]
    return MeasurementsResponse(
        file_id=file_id,
        measurement_crs=record.measurement_crs,
        measurements=measurements,
    )
