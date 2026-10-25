from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
import pytest

from src.database.base import Base
from src.database.engine import Database
from src.database.models import SimulationRun
from src.database.repositories import DuplicateRunError, PostgresSimulationRepository


@pytest.fixture
def repository():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    repo = PostgresSimulationRepository(Database(engine, sessionmaker(engine, expire_on_commit=False)))
    yield repo
    repo.close()


def test_run_create_list_and_duplicate_is_explicit(repository):
    repository.create_run("unit", {"seed": 3}, "shortest_latency", 3, 10.0)
    assert repository.list_runs()[0]["run_id"] == "unit"
    with pytest.raises(DuplicateRunError):
        repository.create_run("unit", {}, "shortest_latency", 3, 10.0)


def test_failed_status_transition_is_persisted(repository):
    repository.create_run("unit", {}, "shortest_latency", 3, 10.0)
    repository.mark_failed("unit", "intentional test failure")
    assert repository.get_run_summary("unit")["status"] == "failed"


def test_session_scope_rolls_back_failed_transaction(repository):
    from src.database.session import session_scope
    with pytest.raises(RuntimeError):
        with session_scope(repository.database.session_factory) as session:
            session.add(SimulationRun(run_id="rollback", status="running", duration_s=1,
                routing_algorithm="x", random_seed=1, configuration={}))
            raise RuntimeError("rollback")
    with session_scope(repository.database.session_factory) as session:
        assert session.scalar(select(SimulationRun).where(SimulationRun.run_id == "rollback")) is None


def test_simulation_results_persist_as_a_complete_historical_run(repository):
    from scripts.run_simulation import build_demo
    engine = build_demo(7, 0.2)
    engine.repository = repository
    result = engine.run()
    summary = repository.get_run_summary(result.run_id)
    assert summary["status"] == "completed"
    assert summary["metrics"]["generated"] == len(result.packets)
    assert repository.get_route_history(result.run_id, result.packets[0].packet_id)
    assert repository.get_event_timeline(result.run_id)
    assert repository.get_metrics(result.run_id)[0].timestamp_s == result.end_time_s
    with pytest.raises(ValueError, match="only be persisted once"):
        repository.persist_results(result)
