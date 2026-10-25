"""Run reproducible paired routing experiments and export measured results."""

import argparse
import json
from dataclasses import asdict

from src.experiments.reporting import export_experiment
from src.experiments.runner import ExperimentRunner
from src.experiments.scenarios import ExperimentConfig, SCENARIOS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="stable_topology")
    parser.add_argument("--algorithm", choices=("both", "shortest_latency", "multi_factor"), default="both")
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--seed-start", type=int, default=7)
    parser.add_argument("--duration", type=float, default=2.0)
    parser.add_argument("--satellites", type=int, default=3)
    parser.add_argument("--traffic-intensity", type=float, default=10.0,
                        help="base Poisson packet arrival rate per second; high-traffic scenario multiplies by 8")
    parser.add_argument("--output-dir", default="experiment_output")
    parser.add_argument("--storage", choices=("local", "postgres"), default="local")
    args = parser.parse_args()
    if args.seeds < 1:
        parser.error("--seeds must be >= 1")
    algorithms = ("shortest_latency", "multi_factor") if args.algorithm == "both" else (args.algorithm,)
    config = ExperimentConfig(scenario=args.scenario,
        seeds=tuple(range(args.seed_start, args.seed_start + args.seeds)),
        duration_s=args.duration, satellite_count=args.satellites,
        traffic_intensity=args.traffic_intensity, algorithms=algorithms,
        output_dir=args.output_dir, storage=args.storage)
    repository = None
    if args.storage == "postgres":
        from src.database.engine import create_database
        from src.database.repositories import PostgresSimulationRepository
        from src.database.schema import initialize_schema
        database = create_database()
        initialize_schema(database)
        repository = PostgresSimulationRepository(database)
    try:
        bundle = ExperimentRunner(config, repository).run()
        bundle = export_experiment(bundle, config.output_dir)
        print(json.dumps({"experiment_id": bundle["experiment_id"],
                          "status": bundle["status"], "storage": bundle["storage"],
                          "completed_runs": sum(r["status"] == "completed" for r in bundle["rows"]),
                          "failed_runs": sum(r["status"] != "completed" for r in bundle["rows"]),
                          "output_dir": config.output_dir}, indent=2))
        if bundle["status"] != "completed":
            raise SystemExit(1)
    finally:
        if repository is not None:
            repository.close()


if __name__ == "__main__":
    main()
