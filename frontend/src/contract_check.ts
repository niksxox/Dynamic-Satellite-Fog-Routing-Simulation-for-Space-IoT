import { FrameMessage, InitMessage, ClientCommand } from './net/types';
import sampleData from '../../docs/sample_frame.json';

// Type-check sample frame directly against FrameMessage
const testFrame: FrameMessage = sampleData as unknown as FrameMessage;

// Type-check a mock Init message
const testInit: InitMessage = {
  type: 'init',
  config: {
    constellation: { T: 120, P: 12, F: 1, inc_deg: 53.0, alt_km: 550.0 },
    isl: { max_range_km: 5000.0, build_frac: 0.92, max_deg: 4 },
    gsl: { el_min_deg: 25.0, k: 3, drop_margin_deg: 2.0 },
    capacity: { isl_mbps: 2000.0, gsl_mbps: 1000.0 },
    failures: { mtbf_link_s: 60000.0, down_s: [20.0, 90.0], intensity: 1.0, detect_delay_s: 1.0 },
    routing: { weights: [1.0, 1.0, 1.0], chunks: 4, stickiness: 0.9, cadence_ticks: 5 },
    sim: { tick_s: 0.1, time_scale: 20.0, seed: 42 },
  },
  ground: [{ id: 120, name: 'Delhi', lat: 28.61, lon: 77.21 }],
  flows: [{ id: 'DEL->LON', src_gs: 120, dst_gs: 121, mbps: 600.0 }],
  nSats: 120,
  planes: [0, 1, 2],
};

const testCmd: ClientCommand = {
  type: 'cmd',
  cmd: 'fail_link',
  args: { a: 0, b: 1 },
};

console.log('Contract check TS passed:', testFrame.t, testInit.type, testCmd.cmd);
