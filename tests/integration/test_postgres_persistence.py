import os

import pytest

from src.database.engine import create_database
from src.database.schema import initialize_schema


@pytest.fixture(scope="module")
def postgres_database():
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL is not configured; PostgreSQL integration database unavailable")
    db = create_database(os.environ["TEST_DATABASE_URL"])
    try:
        with db.engine.connect() as connection:
            name = connection.exec_driver_sql("select current_database()").scalar_one()
        if "test" not in name.lower():
            pytest.skip("TEST_DATABASE_URL must point to a database with 'test' in its name")
        initialize_schema(db)
        yield db
    finally:
        db.dispose()


def test_postgres_schema_creation(postgres_database):
    from sqlalchemy import inspect
    tables = inspect(postgres_database.engine).get_table_names()
    assert {"simulation_runs", "packets", "routes", "simulation_events", "metric_snapshots"} <= set(tables)
