# Dynamic Satellite-Fog Routing Simulation for Space-IoT

Research-oriented simulation of packet routing through a changing network of IoT devices, LEO satellites, ground stations, fog nodes, and a cloud destination. This repository is being built in phases; only the typed model and dynamic topology foundation is implemented so far.

## Phase 1 foundation

- Typed node, link, packet, and simulation configuration models with validation.
- A NetworkX topology engine that connects only modeled node-type pairs within configured ranges.
- Deterministic satellite movement using a circular XY projection. It is a simplified topology model, not high-fidelity orbital mechanics.
- Link properties include distance in km, one-way propagation latency in ms, bandwidth in Mbps, packet-loss probability, congestion, and operational state.
- Distinct physical eligibility and operational availability. Link/node state can be changed explicitly; subsequent topology updates reconcile physical eligibility. An explicit link failure persists across topology updates until a recovery event restores it (`TopologyEngine.set_link_operational(..., True)`).
- Unit tests for geometry, propagation units, satellite movement, compatibility/ranges, state changes, and configuration checks.

Supported link pairs are satellite-satellite, satellite-ground station, ground station-fog, IoT-ground station, IoT-satellite, and fog-cloud. Ranges are configured independently in `config/default.yaml`. No edge is added solely to ensure connectivity.

## Phase 2: routing engine

- `src/routing/engine.py`: Dijkstra routing over the NetworkX topology graph with two modes:
  - `shortest_latency`: minimizes propagation latency plus explicit transmission overhead, plus an optional size-dependent transmission delay when `packet_size_bytes` is given.
  - `multi_factor`: minimizes a normalized convex combination of latency, bandwidth penalty, packet-loss probability, and congestion using the configured `RoutingWeights`. All metrics are min-max normalized across the evaluated network state so raw milliseconds, Mbps, and probabilities are never mixed. Equal min/max values are handled without division by zero.
- `src/routing/__init__.py`: exports `RoutingEngine`, `RoutingMode`, `RoutingResult`.
- `RoutingResult`: structured outcome with source, destination, algorithm, ordered node path, total routing cost, estimated path latency (ms), bottleneck bandwidth (Mbps), estimated delivery reliability, route availability, and a failure reason.
- Only operational nodes and links are traversable; an explicitly failed link is never used even while physically eligible. Unknown endpoints, failed nodes, invalid edge attributes, and disconnected destinations return `route_available=False` with a reason — no route is ever invented.
- Reliability is the product of per-link `(1 - packet_loss_probability)`, a simplified estimate assuming independent losses, not a measured delivery ratio.

### API example

```python
from src.models.config import SimulationConfig
from src.models.network import Node, NodeType, Position
from src.topology.engine import TopologyEngine
from src.routing import RoutingEngine, RoutingMode

cfg = SimulationConfig(iot_ground_range_km=50.0)
topo = TopologyEngine(cfg)
topo.initialize_network([
    Node("iot", NodeType.IOT, Position(0, 0)),
    Node("gs", NodeType.GROUND_STATION, Position(10, 0)),
])

router = RoutingEngine(cfg)
result = router.route(topo.graph, "iot", "gs", RoutingMode.MULTI_FACTOR)
print(result.path, result.estimated_latency_ms, result.bottleneck_bandwidth_mbps,
      result.delivery_reliability, result.route_available)
```

### Metric definitions

- `total_cost`: the optimized objective — path latency in ms for `shortest_latency`, otherwise the normalized multi-factor cost (dimensionless). Kept separate from estimated physical latency.
- `estimated_latency_ms`: sum of link propagation latency plus `transmission_overhead_ms`, plus `packet_size_bytes * 8 / (bandwidth_mbps * 1e6)` seconds in ms when a packet size is provided. No packet size is assumed by default.
- `bottleneck_bandwidth_mbps`: minimum link bandwidth along the path; `inf` for a trivial single-node path.
- `delivery_reliability`: product of `(1 - packet_loss_probability)` over the path; empty path yields `1.0`.
- `route_available`: whether a usable path exists; `reason` explains any failure.

## Setup

Requires Python 3.11 or newer. Create and activate a virtual environment, then install pinned dependencies:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest
```

The full dependency list is pinned for the planned project stack. PostgreSQL is optional until the persistence phase; `.env.example` shows the expected connection variable. Do not put credentials in source control.

## Current limitations

Routing is a static snapshot computation over the current topology graph: there is no SimPy packet forwarding, no time-dependent re-routing during a run, and no per-hop queueing. Reliability assumes independent per-link losses. Satellite motion/topology remains a simplified circular projection, not a validated orbit or coverage model. The dashboard, PostgreSQL persistence, and the complete SimPy simulation have not yet been implemented.
