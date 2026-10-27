"""Traffic flow definitions and path evaluation for constellation simulation.

Provides data structures for traffic flows and multi-path routing evaluation,
along with default end-to-end traffic demand matrix and pure evaluation logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Tuple, Union

from app.sim.conditions import ConditionModel, LinkId, link_key
from app.sim.linkmath import link_latency_ms, survive
from app.sim.topology import Topology

Routes = Dict[str, List[Tuple[List[int], float]]]


@dataclass
class Flow:
    """Traffic flow demand between source and destination nodes."""

    id: str
    src: int
    dst: int
    mbps: float


@dataclass
class FlowEval:
    """Performance evaluation outcome for a single traffic flow."""

    paths: List[Tuple[List[int], float]]
    ms: float
    pdr: float
    blackholed: bool
    delivered_mbps: float


@dataclass
class EvalResult:
    """Network-wide traffic evaluation metrics and link operational states."""

    flows: Dict[str, FlowEval]
    links: Dict[LinkId, Dict[str, Any]]
    lat_ms: float
    pdr: float
    thr_mbps: float


CITY_CODE_MAP = {
    "Delhi": "DEL",
    "London": "LON",
    "New York": "NYC",
    "Sao Paulo": "SAO",
    "Johannesburg": "JNB",
    "Tokyo": "TYO",
    "Sydney": "SYD",
    "Singapore": "SIN",
    "Dubai": "DXB",
    "Los Angeles": "LAX",
}


def _resolve_station_code(name: str) -> str:
    """Resolve ground station name or code to standardized 3-letter code."""
    if name in CITY_CODE_MAP:
        return CITY_CODE_MAP[name]
    for k, v in CITY_CODE_MAP.items():
        if k.lower() == name.lower() or v.lower() == name.lower():
            return v
    return name[:3].upper()


def default_flows(ground: Any) -> List[Flow]:
    """Generate default 8 ground-to-ground traffic demand flows.

    Uses node IDs of ground stations matching standard 3-letter codes:
    DEL, LON, NYC, LAX, SAO, JNB, DXB, SIN, TYO, SYD.

    Flows:
      DEL -> LON : 600 Mbps
      NYC -> SIN : 500 Mbps
      LAX -> TYO : 400 Mbps
      SAO -> JNB : 300 Mbps
      DXB -> SYD : 350 Mbps
      LON -> NYC : 700 Mbps
      SIN -> SYD : 450 Mbps
      DEL -> TYO : 400 Mbps
    """
    station_by_code: Dict[str, int] = {}
    for gs in ground:
        st_id = getattr(gs, "id", None)
        if st_id is None and isinstance(gs, dict):
            st_id = gs["id"]
        st_name = getattr(gs, "name", None)
        if st_name is None and isinstance(gs, dict):
            st_name = gs["name"]
        code = _resolve_station_code(str(st_name))
        station_by_code[code] = st_id

    demands = [
        ("DEL", "LON", 600.0),
        ("NYC", "SIN", 500.0),
        ("LAX", "TYO", 400.0),
        ("SAO", "JNB", 300.0),
        ("DXB", "SYD", 350.0),
        ("LON", "NYC", 700.0),
        ("SIN", "SYD", 450.0),
        ("DEL", "TYO", 400.0),
    ]

    flows: List[Flow] = []
    for src_code, dst_code, rate in demands:
        flows.append(
            Flow(
                id=f"{src_code}-{dst_code}",
                src=station_by_code[src_code],
                dst=station_by_code[dst_code],
                mbps=rate,
            )
        )
    return flows


def evaluate(
    topo: Topology,
    cond: ConditionModel,
    flows: Union[Sequence[Flow], Dict[str, Flow]],
    routes: Routes,
    t: float,
) -> EvalResult:
    """Evaluate network traffic flows across constellation topology snapshot.

    Algorithm:
      1) Check chunk usability: hop (a, b) is usable if link_key(a, b) in topo.isl
         or topo.gsl and cond.is_up(a, b, t). A chunk is blackholed if ANY hop is
         unusable or len(path) < 2.
      2) Accumulate link load: load[link] += chunk.mbps for every hop of every
         non-blackholed chunk.
      3) Link evaluation for every link in topo: capacity from cond.link_props,
         rho = load / capacity, ms = link_latency_ms(prop_ms, rho),
         survive via linkmath.survive(rho), loss = 1 - survive, up = cond.is_up.
      4) Chunk delivery: non-blackholed delivered = mbps * product(survive over hops),
         latency = sum of hop ms. Blackholed chunk delivered = 0.
      5) Flow aggregation: delivered_mbps = sum chunk delivered, ms = delivered-weighted
         mean of chunk latencies (0 if none delivered), pdr = delivered / flow.mbps,
         blackholed = True if flow has no chunks or every chunk is blackholed.
    """
    n_sats = len(topo.pos)

    # Convert flows to a consistent list and dict
    if isinstance(flows, dict):
        flow_list = list(flows.values())
    else:
        flow_list = list(flows)

    # Collect all unique topology links normalized as LinkId (min, max)
    all_topo_links: set[LinkId] = set()
    if topo.isl:
        for u, v in topo.isl:
            all_topo_links.add(link_key(u, v))
    if topo.gsl:
        for u, v in topo.gsl:
            all_topo_links.add(link_key(u, v))

    # 1) A hop (a, b) is usable if link_key(a, b) is in topo.isl or topo.gsl AND cond.is_up(a, b, t).
    #    A chunk is blackholed if ANY hop is unusable, or its path has < 2 nodes.
    chunk_blackholed: Dict[str, List[bool]] = {}
    for f in flow_list:
        chunks = routes.get(f.id, [])
        f_bh: List[bool] = []
        for path, _ in chunks:
            if len(path) < 2:
                f_bh.append(True)
                continue

            hop_failed = False
            for i in range(len(path) - 1):
                u, v = path[i], path[i + 1]
                k = link_key(u, v)
                if k not in all_topo_links or not cond.is_up(u, v, t):
                    hop_failed = True
                    break
            f_bh.append(hop_failed)
        chunk_blackholed[f.id] = f_bh

    # 2) load[link] += chunk.mbps for every hop of every NON-blackholed chunk
    #    (blackholed traffic is dropped and does not load links).
    load: Dict[LinkId, float] = {k: 0.0 for k in all_topo_links}
    for f in flow_list:
        chunks = routes.get(f.id, [])
        for (path, mbps), is_bh in zip(chunks, chunk_blackholed[f.id]):
            if not is_bh:
                for i in range(len(path) - 1):
                    k = link_key(path[i], path[i + 1])
                    load[k] += mbps

    # 3) For EVERY link in topo (not just loaded ones): capacity from cond.link_props,
    #    rho = load/capacity, ms = link_latency_ms(prop_ms, rho), survive via linkmath.survive(rho),
    #    loss = 1 - survive, up = cond.is_up. Down links: up False.
    link_evals: Dict[LinkId, Dict[str, Any]] = {}
    link_surv: Dict[LinkId, float] = {}
    link_delay_ms: Dict[LinkId, float] = {}

    for k in sorted(all_topo_links):
        u, v = k
        props = cond.link_props(topo, u, v)
        capacity = props["capacity_mbps"]
        prop_ms_val = props["prop_ms"]
        kind = props["kind"]

        link_load = load.get(k, 0.0)
        rho = link_load / capacity if capacity > 0 else 0.0
        ms_val = float(link_latency_ms(prop_ms_val, rho))
        survive_val = float(survive(rho))
        loss_val = float(1.0 - survive_val)
        up_val = bool(cond.is_up(u, v, t))

        link_evals[k] = {
            "load": link_load,
            "rho": rho,
            "ms": ms_val,
            "loss": loss_val,
            "up": up_val,
            "kind": kind,
        }
        link_surv[k] = survive_val
        link_delay_ms[k] = ms_val

    # 4 & 5) Evaluate chunks and flows
    flow_evals: Dict[str, FlowEval] = {}
    for f in flow_list:
        chunks = routes.get(f.id, [])
        if not chunks:
            flow_evals[f.id] = FlowEval(
                paths=[],
                ms=0.0,
                pdr=0.0,
                blackholed=True,
                delivered_mbps=0.0,
            )
            continue

        chunk_delivered: List[float] = []
        chunk_latencies: List[float] = []
        all_chunks_bh = True

        for (path, mbps), is_bh in zip(chunks, chunk_blackholed[f.id]):
            if is_bh:
                # Blackholed chunk: delivered 0
                chunk_delivered.append(0.0)
                chunk_latencies.append(0.0)
            else:
                all_chunks_bh = False
                # Non-blackholed chunk: delivered = mbps * product(survive over hops); latency = sum of hop ms
                prod_surv = 1.0
                sum_hop_ms = 0.0
                for i in range(len(path) - 1):
                    k = link_key(path[i], path[i + 1])
                    prod_surv *= link_surv[k]
                    sum_hop_ms += link_delay_ms[k]

                chunk_delivered.append(mbps * prod_surv)
                chunk_latencies.append(sum_hop_ms)

        delivered_mbps = sum(chunk_delivered)
        if delivered_mbps > 0.0:
            flow_ms = (
                sum(d * lat for d, lat in zip(chunk_delivered, chunk_latencies))
                / delivered_mbps
            )
        else:
            flow_ms = 0.0

        pdr = delivered_mbps / f.mbps if f.mbps > 0.0 else 0.0
        blackholed = all_chunks_bh

        flow_evals[f.id] = FlowEval(
            paths=chunks,
            ms=flow_ms,
            pdr=pdr,
            blackholed=blackholed,
            delivered_mbps=delivered_mbps,
        )

    total_delivered = sum(fe.delivered_mbps for fe in flow_evals.values())
    total_offered = sum(f.mbps for f in flow_list)

    if total_delivered > 0.0:
        lat_ms = (
            sum(fe.delivered_mbps * fe.ms for fe in flow_evals.values())
            / total_delivered
        )
    else:
        lat_ms = 0.0

    overall_pdr = (
        (total_delivered / total_offered) if total_offered > 0.0 else 0.0
    )

    return EvalResult(
        flows=flow_evals,
        links=link_evals,
        lat_ms=lat_ms,
        pdr=overall_pdr,
        thr_mbps=total_delivered,
    )
