from __future__ import annotations

import os

from src.database.engine import create_database
from src.database.repositories import PostgresSimulationRepository
from src.database.schema import initialize_schema


def open_repository(storage: str):
    """Return configured PostgreSQL repository, or None for session-local mode."""
    if storage == "local":
        return None
    if storage != "postgres":
        raise ValueError("storage must be local or postgres")
    if not os.getenv("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL is missing. Set it in the environment or choose Local session storage.")
    database = create_database()
    try:
        initialize_schema(database)
    except Exception:
        database.dispose()
        raise
    return PostgresSimulationRepository(database)
