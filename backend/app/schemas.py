from __future__ import annotations
from typing import List, Tuple, Literal, Optional, Union, Dict, Any
from pydantic import BaseModel, Field

# --- Sub-models ---

class ConstellationConfig(BaseModel):
    T: int = 120
    P: int = 12
    F: int = 1
    inc_deg: float = 53.0
    alt_km: float = 550.0

class IslConfig(BaseModel):
    max_range_km: float = 5000.0
    build_frac: float = 0.92
    max_deg: int = 4

class GslConfig(BaseModel):
    el_min_deg: float = 25.0
    k: int = 3
    drop_margin_deg: float = 2.0

class CapacityConfig(BaseModel):
    isl_mbps: float = 2000.0
    gsl_mbps: float = 1000.0

class FailuresConfig(BaseModel):
    mtbf_link_s: float = 60000.0
    down_s: Tuple[float, float] = (20.0, 90.0)
    intensity: float = 1.0
    detect_delay_s: float = 1.0

class RoutingConfig(BaseModel):
    weights: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    chunks: int = 4
    stickiness: float = 0.9
    cadence_ticks: int = 5

class SimParamsConfig(BaseModel):
    tick_s: float = 0.1
    time_scale: float = 20.0
    seed: int = 42

class SimConfig(BaseModel):
    constellation: ConstellationConfig = Field(default_factory=ConstellationConfig)
    isl: IslConfig = Field(default_factory=IslConfig)
    gsl: GslConfig = Field(default_factory=GslConfig)
    capacity: CapacityConfig = Field(default_factory=CapacityConfig)
    failures: FailuresConfig = Field(default_factory=FailuresConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    sim: SimParamsConfig = Field(default_factory=SimParamsConfig)

class GroundStation(BaseModel):
    id: int
    name: str
    lat: float
    lon: float

class Flow(BaseModel):
    id: str
    src_gs: int
    dst_gs: int
    mbps: float

class SatState(BaseModel):
    id: int
    lat: float
    lon: float
    alt: float
    vlat: float
    vlon: float
    st: Literal[0, 1, 2, 3]  # 0 ok, 1 down, 2 eclipse, 3 manual/pinned

class LinkState(BaseModel):
    a: int
    b: int
    k: Literal[0, 1]  # 0 ISL, 1 GSL
    up: Literal[0, 1]
    rho: float
    ms: float
    loss: float

class PathChunk(BaseModel):
    nodes: List[int]
    mbps: float

class FlowEval(BaseModel):
    paths: List[PathChunk]
    ms: float
    pdr: float
    blackholed: bool

class FlowPair(BaseModel):
    id: str
    adaptive: FlowEval
    static: FlowEval

class Metrics(BaseModel):
    latMs: float
    pdr: float
    thrMbps: float
    reroutes: int
    rerouteRate: float
    recoverS: float

class OverallMetrics(BaseModel):
    adaptive: Metrics
    static: Metrics
    linkUptime: float
    activeFailures: int

class SimEvent(BaseModel):
    t: float
    level: Literal['info', 'warn', 'crit']
    kind: str
    msg: str

# --- Server -> Client Messages ---

class InitMessage(BaseModel):
    type: Literal['init'] = 'init'
    config: SimConfig
    ground: List[GroundStation]
    flows: List[Flow]
    nSats: int
    planes: List[int]

class FrameMessage(BaseModel):
    type: Literal['frame'] = 'frame'
    t: float
    scale: float
    running: bool
    tickMs: float
    sats: List[SatState]
    links: List[LinkState]
    flows: List[FlowPair]
    metrics: OverallMetrics
    events: List[SimEvent]

class AckResponse(BaseModel):
    type: Literal['ack'] = 'ack'
    id: Optional[str] = None

class ErrorResponse(BaseModel):
    type: Literal['error'] = 'error'
    msg: str

class OrbitPreviewResponse(BaseModel):
    type: Literal['orbit_preview'] = 'orbit_preview'
    id: int
    track: List[Tuple[float, float]]

ServerMessage = Union[InitMessage, FrameMessage, AckResponse, ErrorResponse, OrbitPreviewResponse]

# --- Client -> Server Commands (Discriminated by cmd) ---

class PlayCmd(BaseModel):
    cmd: Literal['play'] = 'play'

class PauseCmd(BaseModel):
    cmd: Literal['pause'] = 'pause'

class ResetCmd(BaseModel):
    cmd: Literal['reset'] = 'reset'

class SetScaleCmd(BaseModel):
    cmd: Literal['set_scale'] = 'set_scale'
    scale: float

class SetWeightsCmd(BaseModel):
    cmd: Literal['set_weights'] = 'set_weights'
    a: float
    b: float
    c: float

class SetParamsCmd(BaseModel):
    cmd: Literal['set_params'] = 'set_params'
    params: Dict[str, Any]

class FailLinkCmd(BaseModel):
    cmd: Literal['fail_link'] = 'fail_link'
    a: int
    b: int
    duration_s: Optional[float] = None

class RestoreLinkCmd(BaseModel):
    cmd: Literal['restore_link'] = 'restore_link'
    a: int
    b: int

class FailSatCmd(BaseModel):
    cmd: Literal['fail_sat'] = 'fail_sat'
    id: int

class RestoreSatCmd(BaseModel):
    cmd: Literal['restore_sat'] = 'restore_sat'
    id: int

class MoveSatCmd(BaseModel):
    cmd: Literal['move_sat'] = 'move_sat'
    id: int
    lat: float
    lon: float

class MoveGsCmd(BaseModel):
    cmd: Literal['move_gs'] = 'move_gs'
    id: int
    lat: float
    lon: float

class PreviewOrbitCmd(BaseModel):
    cmd: Literal['preview_orbit'] = 'preview_orbit'
    id: int
    lat: float
    lon: float

class SetFlowScaleCmd(BaseModel):
    cmd: Literal['set_flow_scale'] = 'set_flow_scale'
    factor: float

class AddFlowCmd(BaseModel):
    cmd: Literal['add_flow'] = 'add_flow'
    src: int
    dst: int
    mbps: float

class RemoveFlowCmd(BaseModel):
    cmd: Literal['remove_flow'] = 'remove_flow'
    id: str

CommandPayload = Union[
    PlayCmd, PauseCmd, ResetCmd, SetScaleCmd, SetWeightsCmd, SetParamsCmd,
    FailLinkCmd, RestoreLinkCmd, FailSatCmd, RestoreSatCmd, MoveSatCmd,
    MoveGsCmd, PreviewOrbitCmd, SetFlowScaleCmd, AddFlowCmd, RemoveFlowCmd
]

class ClientCommand(BaseModel):
    type: Literal['cmd'] = 'cmd'
    cmd: str
    args: Dict[str, Any] = Field(default_factory=dict)
    id: Optional[str] = None
