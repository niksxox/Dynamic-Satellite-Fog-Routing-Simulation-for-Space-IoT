# Dynamic Satellite-Fog Routing Simulation for Space-IoT

Research simulation of packets routed through a changing graph of IoT devices, LEO satellites, ground stations, fog nodes, and a cloud destination. It is a software model, not a satellite-control system.

## Implemented phases

### Phase 1: models and topology

Typed node, link, packet, and configuration models; a NetworkX topology engine; configured physical link ranges; explicit node and link availability; and deterministic circular satellite movement in a Cartesian XY projection. The orbital projection is a simple, replaceable approximation, not validated orbital mechanics.

Supported link pairs: satellite-satellite, satellite-ground station, ground station-fog, IoT-ground station, IoT-satellite, and fog-cloud. Link distances use kilometers, propagation latency uses milliseconds, bandwidth uses decimal Mbps, and packet size uses bytes.

### Phase 2: routing

`src/routing/engine.py` provides two Dijkstra modes:

- `shortest_latency`: propagation plus explicit overhead and, when a packet size is supplied, size-dependent serialization latency.
- `multi_factor`: nonnegative weighted cost from normalized latency, bandwidth penalty, packet loss, and congestion. The cost is dimensionless and separate from estimated physical latency.

Only operational nodes and links can be routed. `RoutingResult` includes path, cost, estimated latency, bottleneck bandwidth, estimated reliability, availability, and a no-route reason. Reliability multiplies per-link success probabilities and assumes independent losses.

### Phase 3: SimPy simulation and rerouting

`SimulationEngine` runs headlessly with one SimPy virtual-time environment. It coordinates topology refresh, Poisson or scheduled traffic, hop-by-hop forwarding, link/node failures and recovery, fog service, route decisions, structured events, and metrics.

Traffic uses exponential inter-arrival times for a Poisson process unless a deterministic `schedule_s` tuple is supplied. Each source receives a separate seeded random stream. Packet IDs are deterministic within a run.

The default link model is full duplex: each direction has an independent capacity-one serialization resource. `half_duplex_links: true` makes opposite directions share the resource. Serialization time is `packet_size_bytes * 8 / (bandwidth_mbps * 1,000,000)` seconds. The channel resource is held for serialization and configured overhead; propagation is in flight and may overlap other transmissions.

An already-started frame completes its serialization and propagation if its link fails. A packet waiting for the link checks availability after acquiring the resource. At the next forwarding decision, an unavailable hop triggers a route computation from the packet's current node. Route computation has a configurable simulated delay (`route_computation_delay_ms`); a reroute count increments only when a valid replacement route is selected. If a recovery attempt exhausts its configured retries, the packet is dropped. Initial no-route attempts wait for a topology interval and are bounded by the same retry setting.

Fog nodes use a shared SimPy resource with `fog_default_servers` capacity. Service time is the larger of configured `processing_delay_ms` and `1 / processing_capacity_pps` when a processing rate is configured. Queue wait is measured from the actual resource request and reported separately. Route estimates do not include fog service delay, so measured end-to-end delay counts it only when the packet is processed.

Packets end as delivered, dropped, timed out, or `PENDING`. `PENDING` is a right-censored packet still active at the simulation horizon; it is not counted as a delivery or assigned a latency. PDR is delivered/generated, including pending packets in the denominator. Goodput is delivered payload bits divided by the full simulation observation window. Recovery time is route-selection time minus failure-detection time; failed recoveries have a separate count and no zero duration.

Delivered-packet latency includes mean and median for any nonempty sample. The p95 field is left undefined until there are at least 20 delivered samples.

In-memory packet and event records are capped by `max_generated_packets` and `max_event_records` in the config. The result indicates if the event cap truncated the log. Packet records are retained up to the packet cap.

## Setup and commands

Requires Python 3.11 or newer. Create a virtual environment and install the pinned stack:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Run the deterministic two-satellite failure/recovery example from the repository root:

```powershell
python -m scripts.run_simulation --seed 7 --duration 0.2
```

Run all tests:

```powershell
python -m pytest -q
```

Phase 3 verification in the implementation environment: `python -m pytest -q` completed with **40 passed**. The documented demo command completed with 3 generated, 3 delivered, 0 dropped, and 1 reroute; measured mean latency was 0.0066039 s and route recovery time was 0.001 s. These are demonstration-run observations, not an algorithm comparison or performance claim.

The runnable API is `SimulationEngine(config, nodes, traffic, failures=...).run()`. Structured packet records, events, decisions, topology/resource statistics, and metric summaries are returned in `SimulationResults`. `FailureSchedule` supports link/node failure and recovery, fog overload/recovery, congestion changes, and packet-loss changes.

### Phase 4: PostgreSQL persistence

Install the pinned requirements, then create a PostgreSQL database and set `DATABASE_URL`. `.env.example` shows the format; copy it to `.env` and replace the placeholders (the project does not automatically load `.env`, so export the variable in your shell or IDE).

```sql
CREATE DATABASE satellite_sim;
```

Initialize missing tables without removing run history, then run with persistence:

```powershell
python -m scripts.init_db
python -m scripts.run_simulation --seed 7 --duration 0.2 --storage postgres
```

`--storage auto` uses PostgreSQL when `DATABASE_URL` is set and otherwise uses the clearly reported volatile `in_memory_demo` backend. Use `--storage memory` to select it explicitly. In-memory data is lost when the process exits. Persistence writes use a separate initial configuration transaction and one final bounded batch transaction; the run is completed only after the latter commits. A failed final write leaves the run non-completed and surfaces the error. Events and route decisions are append-only per run; the links table stores configured/current edge attributes, not historical topology by itself. Virtual time is seconds from simulation start; wall-clock audit timestamps are timezone aware. Node/packet/route references are scoped by run; run IDs are unique globally.

The schema is version-controlled in `src/database/models.py` and records version 1 in `schema_version`. Initialization is additive and never deletes historical records. Future schema evolution should add an explicit versioned migration before changing an existing deployment.

Repository methods `list_runs()`, `get_run_summary(run_id)`, `get_route_history(run_id, packet_id)`, `get_event_timeline(run_id)`, and `get_metrics(run_id)` support historical review. Packet outcome counts use generated packets as the eligible population; pending packets are right-censored and remain in the PDR denominator as specified by Phase 3. Mean/median latency use delivered packets only; undefined latency/PDR values are stored as `NULL`. Throughput is delivered payload bits divided by the full observation window. Config snapshots make scenario differences visible; comparisons should use compatible configurations and seeds.

For example, query final outcomes and latency from delivered packets, plus reroute and successful recovery event counts:

```sql
SELECT r.run_id, r.routing_algorithm, r.random_seed,
       m.generated, m.delivered, m.dropped, m.timed_out, m.pending, m.pdr,
       (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY p.latency_s)
          FROM packets p WHERE p.run_id = r.run_id AND p.final_state = 'delivered') AS median_latency_s,
       (SELECT count(*) FROM routes rt WHERE rt.run_id = r.run_id AND rt.cause NOT IN ('initial', 'retry')) AS route_changes,
       (SELECT count(*) FROM simulation_events e WHERE e.run_id = r.run_id
          AND e.event_type IN ('link_recovery', 'node_recovery', 'fog_recovery')) AS recovery_events
FROM simulation_runs r
LEFT JOIN metric_snapshots m ON m.run_id = r.run_id AND m.timestamp_s = r.simulation_end_s
WHERE r.status = 'completed';
```

Use the same seed and configuration JSON when comparing routing algorithms; inspect those snapshots and exclude incompatible scenarios. Export with `psql` `\copy (...) TO 'runs.csv' CSV HEADER` or serialize results returned by the repository methods.

To run the PostgreSQL integration test, provision an isolated database whose name contains `test` and set `TEST_DATABASE_URL`. Without that dedicated database the integration test is explicitly skipped. SQLite is used only by unit tests to exercise ORM/repository transactions; it is not a supported runtime backend. Export queried data with PostgreSQL `COPY`/`psql` or the repository APIs. Common connection errors usually mean the server is stopped, the database name/user/password is wrong, or the host/port is unreachable. Never commit real credentials or `.env` files.

## Model limitations and remaining phases

Satellite motion is a deterministic circular projection, not a validated orbit or geographic line-of-sight model. The graph updates at configured intervals. Shared link resources limit serialization but do not model a lower-layer retransmission protocol. Packet loss drops the packet without retransmission. Fog overload currently marks the fog node unavailable; it does not dynamically reduce its service rate. Multi-factor weights normalize against the current usable edge set, so route costs are relative to that snapshot. Phase 3 does not emit periodic position, queue-length, or utilization snapshots, so Phase 4 persists initial node configuration, observed topology events, and final fog statistics; it cannot reconstruct unsampled positions. Dashboard and full experiment orchestration remain later phases.
