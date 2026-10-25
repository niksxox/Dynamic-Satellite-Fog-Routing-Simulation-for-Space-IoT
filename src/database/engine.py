from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import sessionmaker


class DatabaseConfigurationError(ValueError):
    """Missing or invalid database configuration."""


@dataclass
class Database:
    engine: Engine
    session_factory: sessionmaker

    def dispose(self) -> None:
        self.engine.dispose()


def create_database(url: str | None = None) -> Database:
    """Create a pooled PostgreSQL engine; never includes credentials in errors."""
    raw = url if url is not None else os.getenv("DATABASE_URL")
    if not raw:
        raise DatabaseConfigurationError(
            "DATABASE_URL is not set. Configure a PostgreSQL URL or use --storage memory."
        )
    try:
        parsed = make_url(raw)
    except Exception as exc:
        raise DatabaseConfigurationError("DATABASE_URL is malformed.") from exc
    if parsed.drivername == "postgresql":
        parsed = parsed.set(drivername="postgresql+psycopg")
    if parsed.drivername != "postgresql+psycopg":
        raise DatabaseConfigurationError("DATABASE_URL must use PostgreSQL with psycopg 3.")
    if not parsed.host or not parsed.database:
        raise DatabaseConfigurationError("DATABASE_URL must include a host and database name.")
    engine = create_engine(parsed, pool_size=5, max_overflow=10, pool_pre_ping=True,
                           pool_recycle=1800)
    return Database(engine, sessionmaker(bind=engine, expire_on_commit=False))
