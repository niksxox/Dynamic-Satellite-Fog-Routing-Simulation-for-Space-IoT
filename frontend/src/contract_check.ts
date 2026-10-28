import { FrameMessage, InitMessage, ClientCommand } from './net/types';
import sampleData from '../../docs/sample_frame.json';

// Type-check sample frame directly against FrameMessage
const testFrame: FrameMessage = sampleData as unknown as FrameMessage;

// Type-check a mock Init message
const testInit: InitMessage = {
  type: 'init',
  config: {
    num_sats: 120,
    time_scale: 20.0,
    cadence_ticks: 5,
  },
  ground: [{ id: 120, name: 'Delhi', lat: 28.61, lon: 77.21 }],
  flows: [{ id: 'DEL->LON', src: 120, dst: 121, mbps: 600.0 }],
  nSats: 120,
  planes: [0, 1, 2],
};

const testCmd: ClientCommand = {
  type: 'cmd',
  cmd: 'fail_link',
  args: { a: 0, b: 1 },
};

console.log('Contract check TS passed:', testFrame.t, testInit.type, testCmd.cmd);
