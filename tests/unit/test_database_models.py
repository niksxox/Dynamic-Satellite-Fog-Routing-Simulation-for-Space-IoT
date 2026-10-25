from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.base import Base
from src.database.models import MetricSnapshot, SimulationRun


def test_schema_has_expected_constraints_and_indexes():
    assert "ck_run_status" in {c.name for c in SimulationRun.__table__.constraints}
    assert "uq_metric_run_time" in {c.name for c in MetricSnapshot.__table__.constraints}
    assert "ix_metrics_run_time" in {i.name for i in MetricSnapshot.__table__.indexes}


def test_schema_creates_on_sqlite_for_unit_level_ddl_only():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    assert "packets" in Base.metadata.tables
    engine.dispose()
