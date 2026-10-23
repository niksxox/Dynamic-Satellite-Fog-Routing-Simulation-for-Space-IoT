# Dynamic Satellite-Fog Routing Simulation for Space-IoT

Research-oriented simulation of packet routing through a changing network of IoT devices, LEO satellites, ground stations, fog nodes, and a cloud destination. This repository is being built in phases; only the typed model and dynamic topology foundation is implemented so far.

## Phase 1 foundation

- Typed node, link, packet, and simulation configuration models with validation.
- A NetworkX topology engine that connects only modeled node-type pairs within configured ranges.
- Deterministic satellite movement using a circular XY projection. It is a simplified topology model, not high-fidelity orbital mechanics.
- Link properties include distance in km, one-way propagation latency in ms, bandwidth in Mbps, packet-loss probability, congestion, and operational state.
- Distinct physical eligibility and operational availability. Link/node state can be changed explicitly; subsequent topology updates reconcile physical eligibility.
- Unit tests for geometry, propagation units, satellite movement, compatibility/ranges, state changes, and configuration checks.

Supported link pairs are satellite-satellite, satellite-ground station, ground station-fog, IoT-ground station, IoT-satellite, and fog-cloud. Ranges are configured independently in `config/default.yaml`. No edge is added solely to ensure connectivity.

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

Routing, packet forwarding, SimPy processes, persistence, experiments, and the dashboard have not yet been implemented. The current topology stores one snapshot and updates positions when `TopologyEngine.update_topology(time_s)` is called. Satellite motion is a deterministic circular projection in a shared Cartesian frame and should not be interpreted as a validated orbit or geographic coverage model.
