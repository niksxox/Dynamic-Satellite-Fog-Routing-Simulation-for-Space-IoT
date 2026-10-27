"""Simulation demo for constellation network topology over an orbital period."""

import itertools
from typing import Dict, List, Tuple
import networkx as nx
import numpy as np

from app.sim.constants import (
    ATMOS_KM,
    GSL_DROP_MARGIN_DEG,
    GSL_EL_MIN_DEG,
    GSL_MAX_PER_STATION,
    ISL_BUILD_FRAC,
    ISL_MAX_DEGREE,
    ISL_MAX_RANGE_KM,
)
from app.sim.orbit import positions_ecef, walker_delta
from app.sim.topology import (
    TopoParams,
    Topology,
    build_topology,
    default_ground_stations,
    elevation_deg,
)


def run_topology_simulation(
    params: TopoParams,
    t_start: float = 0.0,
    t_end: float = 5730.0,
    step: float = 30.0,
) -> Tuple[
    float,
    float,
    Dict[str, Tuple[int, float, float]],
    Dict[Tuple[str, str], float],
    float,
]:
    """Simulate constellation topology over time, returning connectivity statistics.

    Returns:
        (avg_isl_count, avg_isl_degree, station_visibility_stats, pair_connectivity, min_pair_pct)
        where station_visibility_stats maps station_name -> (min_visible, avg_visible, pct_with_gsl)
    """
    constellation = walker_delta(120, 12, 1, 53, 550)
    ground = default_ground_stations(120)
    n_sats = len(constellation)
    g_stations = len(ground)

    t_values = np.arange(t_start, t_end + 1e-6, step)
    n_samples = len(t_values)

    isl_counts: List[int] = []
    isl_degrees: List[float] = []

    # station_idx -> list of visible sat counts per timestep
    station_visible: Dict[int, List[int]] = {i: [] for i in range(g_stations)}
    # station_idx -> count of timesteps with at least 1 GSL
    station_has_gsl: Dict[int, int] = {i: 0 for i in range(g_stations)}

    # All 45 station pairs: (gs_a.id, gs_b.id) -> count of connected samples
    pairs = list(itertools.combinations(ground, 2))
    connected_counts: Dict[Tuple[int, int], int] = {
        (gs_a.id, gs_b.id): 0 for gs_a, gs_b in pairs
    }

    prev: Topology = None
    ground_pos = np.stack([gs.ecef for gs in ground], axis=0)  # (G, 3)

    for t in t_values:
        sat_pos = positions_ecef(constellation, float(t))
        topo = build_topology(sat_pos, ground, prev=prev, params=params)
        prev = topo

        # 1. ISL statistics
        n_isl = len(topo.isl)
        isl_counts.append(n_isl)
        isl_degrees.append((2.0 * n_isl) / n_sats)

        # 2. Geometric visibility per station (el >= el_min_deg)
        el_matrix = elevation_deg(
            ground_pos[:, np.newaxis, :],
            sat_pos[np.newaxis, :, :],
        )  # (G, N)
        for g_idx, gs in enumerate(ground):
            vis = int(np.sum(el_matrix[g_idx] >= params.el_min_deg))
            station_visible[g_idx].append(vis)
            # Check if this station has at least 1 GSL
            if any(link[1] == gs.id for link in topo.gsl):
                station_has_gsl[g_idx] += 1

        # 3. Network graph connectivity
        g = nx.Graph()
        for gs in ground:
            g.add_node(gs.id)
        g.add_edges_from(topo.isl)
        g.add_edges_from(topo.gsl)

        # Precompute connected components for fast path queries
        components = list(nx.connected_components(g))
        node_to_comp = {}
        for comp_idx, comp in enumerate(components):
            for node in comp:
                node_to_comp[node] = comp_idx

        for gs_a, gs_b in pairs:
            if node_to_comp.get(gs_a.id) == node_to_comp.get(gs_b.id):
                connected_counts[(gs_a.id, gs_b.id)] += 1

    avg_isl = float(np.mean(isl_counts))
    avg_deg = float(np.mean(isl_degrees))

    # Compile visibility stats: name -> (min_vis, avg_vis, pct_with_gsl)
    visibility_stats: Dict[str, Tuple[int, float, float]] = {}
    for g_idx, st in enumerate(ground):
        counts = station_visible[g_idx]
        pct_gsl = (station_has_gsl[g_idx] / n_samples) * 100.0
        visibility_stats[st.name] = (min(counts), float(np.mean(counts)), pct_gsl)

    # Compile pair connectivity percentages
    pair_percentages: Dict[Tuple[str, str], float] = {}
    pct_list: List[float] = []
    for gs_a, gs_b in pairs:
        cnt = connected_counts[(gs_a.id, gs_b.id)]
        pct = (cnt / n_samples) * 100.0
        pair_percentages[(gs_a.name, gs_b.name)] = pct
        pct_list.append(pct)

    min_pair_pct = min(pct_list) if pct_list else 0.0

    return avg_isl, avg_deg, visibility_stats, pair_percentages, min_pair_pct


def print_simulation_report(
    params: TopoParams,
    avg_isl: float,
    avg_deg: float,
    vis_stats: Dict[str, Tuple[int, float, float]],
    pair_pcts: Dict[Tuple[str, str], float],
    min_pair_pct: float,
) -> None:
    print("=" * 75)
    print("Constellation Topology Simulation Over One Orbit (t=0 to 5730s, dt=30s)")
    print(
        f"Parameters: el_min={params.el_min_deg} deg, max_deg={params.max_deg}, "
        f"isl_max_range={params.isl_max_range_km} km, atmos={params.atmos_km} km, "
        f"drop_margin={params.gsl_drop_margin_deg} deg"
    )
    print("=" * 75)

    print(f"\nAverage ISL Count:  {avg_isl:.2f}")
    print(f"Average ISL Degree: {avg_deg:.2f}")

    print("\n--- Ground Station Satellite Visibility & GSL Coverage ---")
    print(
        f"{'Station':<15} | {'Min Visible':<12} | {'Avg Visible':<12} | {'Samples with >= 1 GSL (%)':<25}"
    )
    print("-" * 72)
    for name, (min_v, avg_v, pct_gsl) in vis_stats.items():
        print(f"{name:<15} | {min_v:<12} | {avg_v:<12.2f} | {pct_gsl:22.2f}%")

    print("\n--- Ground Station Pair Connectivity (45 Pairs) ---")
    print(f"{'Station Pair':<32} | {'Connected Samples (%)':<22}")
    print("-" * 58)
    for (st_a, st_b), pct in sorted(pair_pcts.items()):
        pair_str = f"{st_a} - {st_b}"
        print(f"{pair_str:<32} | {pct:6.2f}%")

    print("-" * 58)
    print(f"Overall Minimum Pair Connectivity: {min_pair_pct:.2f}%")
    print("=" * 75)


def main() -> None:
    params = TopoParams()
    avg_isl, avg_deg, vis_stats, pair_pcts, min_pair_pct = run_topology_simulation(params)
    print_simulation_report(params, avg_isl, avg_deg, vis_stats, pair_pcts, min_pair_pct)


if __name__ == "__main__":
    main()
