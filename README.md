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

### Phase 5: reproducible algorithm experiments

The research question is whether `multi_factor` routing changes measured packet outcomes versus the `shortest_latency` Dijkstra baseline under matched network conditions. The framework does not assume the weighted algorithm wins. Both are existing Dijkstra routers; only their route cost differs. Each paired seed reconstructs the same topology, traffic parameters, duration, mobility, failure schedule, resource settings, and seed for each algorithm. Traffic uses per-source seeded streams. Packet-loss draws are now deterministic by seed, packet, link, and per-packet link-attempt index, so a route using another link cannot shift unrelated random draws. Different paths may still create different contention and outcomes.

The scenario registry provides stable topology, normal satellite mobility, inter-satellite link failure, satellite node failure, congestion spike, fog-node overload, high traffic load, and simultaneous failures. Satellite layout obeys the existing compatibility and range model; the deterministic circular orbit remains a simplified projection. Failure events are checked in the emitted simulation event log and recorded per run. Durations, satellite count, traffic intensity, and seeds are configurable.

Run a quick paired experiment (3 seeds, both algorithms) and export results:

```powershell
python -m scripts.run_experiment --scenario stable_topology --seeds 3 --seed-start 7 --duration 2 --satellites 3 --traffic-intensity 10 --storage local --output-dir experiment_output
```

Choose any scenario with `--scenario`; choose `--algorithm shortest_latency` or `--algorithm multi_factor` for one algorithm; change the seed count/start, duration, satellite count, traffic rate, and output directory with the corresponding options. Local mode writes explicitly labeled JSON, per-run CSV, aggregated CSV, paired-difference CSV, Markdown, and Plotly HTML charts. It does not persist simulation records to PostgreSQL. Use `--storage postgres` with configured `DATABASE_URL` to initialize the additive schema and persist both simulations and experiment records.

Latency statistics use delivered packets only; measured packet latency includes transmission serialization, configured overhead, propagation, queueing/service at fog, route-computation delay, and rerouting delay. PDR is delivered/generated; pending packets are censored at the fixed full-duration observation window and remain in the denominator. Effective throughput is delivered payload bits per full observation window, in decimal Mbps. Recovery includes only successful detection-to-valid-route samples; failed recoveries have a count but no zero duration. Packet-loss rate is lost frames divided by transmission attempts. Drop and timeout rates use generated packets. Per-run wall-clock runtime is reported separately from network metrics. Route-computation CPU time and time-integrated link availability are currently unavailable. The report gives valid sample counts, failures, variability, and exploratory paired t intervals; small samples do not establish statistical significance. Failed runs remain in exports and aggregates.

The generated actual demonstration run is in `experiment_output/exp-f8a13bdd78b74a93a956d6915ad11ad4_report.md` and its JSON/CSV/HTML outputs. For 3 seeds on the 2-second stable scenario (3 satellites, 10 packets/s base intensity), both algorithms completed all 3 runs: mean delivered latency **4.1773 ms**, PDR **1.0**, and effective throughput **0.048469 Mbps** for each. In this stable case the measured means match; this is not evidence of a general advantage. A one-seed smoke experiment also ran both algorithms across all eight scenarios; all 16 runs completed and each scheduled failure scenario recorded its expected failure/change event.

Charts are made only from actual completed run metrics. This command evaluates one traffic intensity and one network size at a time; cross-intensity and cross-size sweep charts are not generated from a single experiment. Repeat with different settings and combine exports for such analyses. Per-run results are held in memory until export; do not request very large sweeps in one process.

## Model limitations and remaining phases

Satellite motion is a deterministic circular projection, not a validated orbit or geographic line-of-sight model. The graph updates at configured intervals. Shared link resources limit serialization but do not model a lower-layer retransmission protocol. Packet loss drops the packet without retransmission. Fog overload currently marks the fog node unavailable; it does not dynamically reduce its service rate. Multi-factor weights normalize against the current usable edge set, so route costs are relative to that snapshot. Phase 3 does not emit periodic position, queue-length, or utilization snapshots, so Phase 4 persists initial node configuration, observed topology events, and final fog statistics; it cannot reconstruct unsampled positions. The Streamlit dashboard remains future work.
