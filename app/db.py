"""Database setup: SQLite engine, session factory, FastAPI dependency."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    """Lazily create the SQLAlchemy engine (honours env-based settings)."""
    global _engine
    if _engine is None:
        connect_args = (
            {"check_same_thread": False}
            if settings.DATABASE_URL.startswith("sqlite")
            else {}
        )
        _engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
    return _engine


def session_factory() -> sessionmaker:
    """Lazily create the session factory bound to the engine."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False
        )
    return _SessionLocal


def init_db() -> None:
    """Create all tables. Importing models registers them on Base first."""
    from app import models  # noqa: F401  (side-effect: model registration)

    Base.metadata.create_all(get_engine())


def get_db() -> Iterator[Session]:
    """FastAPI dependency providing a request-scoped DB session."""
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()
