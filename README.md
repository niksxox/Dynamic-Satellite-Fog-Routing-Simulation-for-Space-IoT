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

`SimulationEngine` runs headlessly with one SimPy virtual-time environment. It coordinates topology refresh, Poisson or scheduled traffic, hop-by-hop forwarding, link/node failures and recovery, fog service, route decisions, structured events, and metrics. PostgreSQL, Streamlit, and experiment orchestration are not part of this phase.

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

PostgreSQL settings are shown in `.env.example`; database setup remains for a later phase. Never commit credentials or `.env` files.

## Model limitations and remaining phases

Satellite motion is a deterministic circular projection, not a validated orbit or geographic line-of-sight model. The graph updates at configured intervals. Shared link resources limit serialization but do not model a lower-layer retransmission protocol. Packet loss drops the packet without retransmission. Fog overload currently marks the fog node unavailable; it does not dynamically reduce its service rate. Multi-factor weights normalize against the current usable edge set, so route costs are relative to that snapshot. Persistence, experiments, CSV exports, and the dashboard remain future work.
