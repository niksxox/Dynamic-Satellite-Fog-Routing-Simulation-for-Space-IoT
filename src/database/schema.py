from sqlalchemy import select

from src.database.base import Base
from src.database.models import SchemaVersion
from src.database.session import session_scope

SCHEMA_VERSION = 1


def initialize_schema(database) -> None:
    """Create missing tables and record the version; existing history is retained."""
    Base.metadata.create_all(database.engine)
    with session_scope(database.session_factory) as session:
        if session.scalar(select(SchemaVersion).where(SchemaVersion.version == SCHEMA_VERSION)) is None:
            session.add(SchemaVersion(version=SCHEMA_VERSION))
