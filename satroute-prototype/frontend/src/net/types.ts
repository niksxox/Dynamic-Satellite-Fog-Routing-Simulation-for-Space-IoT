// SatRoute TypeScript types mirror the payload emitted by backend/app.
export interface SimConfig {
  num_sats: number;
  time_scale: number;
  cadence_ticks: number;
}

export interface GroundStation {
  id: number;
  name: string;
  lat: number;
  lon: number;
}

export interface Flow {
  id: string;
  src: number;
  dst: number;
  mbps: number;
}

export interface SatState {
  id: number;
  lat: number;
  lon: number;
  alt: number;
  vlat: number;
  vlon: number;
  st: 0 | 1 | 2 | 3; // 0 ok, 1 down, 2 eclipse, 3 manual/pinned
}

export interface LinkState {
  a: number;
  b: number;
  k: 0 | 1; // 0 ISL, 1 GSL
  up: 0 | 1;
  rho: number;
  ms: number;
  loss: number;
}

export interface PathChunk {
  nodes: number[];
  mbps: number;
}

export interface FlowEval {
  paths: PathChunk[];
  ms: number;
  pdr: number;
  blackholed: boolean;
}

export interface FlowPair {
  id: string;
  adaptive: FlowEval;
  static: FlowEval;
}

export interface Metrics {
  latMs: number;
  pdr: number;
  thrMbps: number;
  reroutes: number;
  rerouteRate: number;
  recoverS: number;
}

export interface OverallMetrics {
  adaptive: Metrics;
  static: Metrics;
  linkUptime: number;
  activeFailures: number;
}

export interface SimEvent {
  t: number;
  level: 'info' | 'warn' | 'crit';
  kind: string;
  msg: string;
}

// Server -> Client Messages
export interface InitMessage {
  type: 'init';
  config: SimConfig;
  ground: GroundStation[];
  flows: Flow[];
  nSats: number;
  planes: number[];
}

export interface FrameMessage {
  type: 'frame';
  positionSource?: 'simulation' | 'tle';
  t: number;
  scale: number;
  running: boolean;
  tickMs: number;
  sats: SatState[];
  links: LinkState[];
  flows: FlowPair[];
  metrics: OverallMetrics;
  events: SimEvent[];
}

export interface AckResponse {
  type: 'ack';
  id?: string;
}

export interface ErrorResponse {
  type: 'error';
  msg?: string;
  error?: string;
  id?: string | number;
}

export interface OrbitPreviewResponse {
  type: 'orbit_preview';
  id?: number;
  track?: [number, number][];
}

export type ServerMessage =
  | InitMessage
  | FrameMessage
  | AckResponse
  | ErrorResponse
  | OrbitPreviewResponse;

// Client -> Server Command definitions
export type CommandName =
  | 'play'
  | 'pause'
  | 'reset'
  | 'set_scale'
  | 'set_weights'
  | 'set_params'
  | 'fail_link'
  | 'restore_link'
  | 'fail_sat'
  | 'restore_sat'
  | 'move_sat'
  | 'move_gs'
  | 'preview_orbit'
  | 'set_flow_scale'
  | 'add_flow'
  | 'remove_flow';

export interface ClientCommand {
  type: 'cmd';
  cmd: CommandName;
  args?: Record<string, unknown>;
  id?: string | number;
}

export interface TrackedSatelliteInfo {
  id: number;
  norad_id: number;
  name: string;
}

export interface TrackingStatus {
  available: boolean;
  source: string;
  refreshed_at: string | null;
  oldest_tle_epoch: string | null;
  data_age_seconds: number | null;
  satellite_count: number;
  satellites: TrackedSatelliteInfo[];
  error: string | null;
}

export interface GroundTrack {
  satellite_id: number;
  norad_id: number;
  name: string;
  start: string;
  end: string;
  track: [number, number][];
}
