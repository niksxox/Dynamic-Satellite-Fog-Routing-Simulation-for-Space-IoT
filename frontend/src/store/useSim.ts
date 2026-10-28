import { create } from 'zustand';
import {
  CommandName,
  FrameMessage,
  GroundTrack,
  InitMessage,
  ServerMessage,
  TrackingStatus,
} from '../net/types';
import { socket } from '../net/socket';

export type ViewMode = 'adaptive' | 'static' | 'compare';
export type OrbitMode = 'simulation' | 'live' | 'combined';

export type SelectionType =
  | { type: 'sat'; id: number }
  | { type: 'gs'; id: number }
  | { type: 'link'; a: number; b: number }
  | null;

interface UIState {
  view: ViewMode;
  selection: SelectionType;
  selectedFlowId: string | null;
  dragging: number | null;
  tab: 'network' | 'controls' | 'performance' | 'logs';
  orbitMode: OrbitMode;
}

interface SimStore {
  init: InitMessage | null;
  latestFrame: FrameMessage | null;
  prevFrame: FrameMessage | null;
  recvAt: number;
  connected: boolean;
  fps: number;
  lastError: string | null;
  trackingStatus: TrackingStatus | null;
  trackingError: string | null;
  groundTrack: GroundTrack | null;
  ui: UIState;

  // Actions
  setInit: (init: InitMessage) => void;
  setFrame: (frame: FrameMessage) => void;
  setConnected: (connected: boolean) => void;
  setFps: (fps: number) => void;
  setError: (message: string | null) => void;
  setTrackingStatus: (status: TrackingStatus | null) => void;
  setTrackingError: (message: string | null) => void;
  setGroundTrack: (track: GroundTrack | null) => void;
  setView: (view: ViewMode) => void;
  setOrbitMode: (mode: OrbitMode) => void;
  setSelection: (selection: SelectionType) => void;
  setSelectedFlowId: (flowId: string | null) => void;
  setDragging: (id: number | null) => void;
  setTab: (tab: 'network' | 'controls' | 'performance' | 'logs') => void;
  sendCommand: (cmd: CommandName, args?: Record<string, unknown>, id?: string | number) => void;
}

export const useSimStore = create<SimStore>((set, get) => ({
  init: null,
  latestFrame: null,
  prevFrame: null,
  recvAt: 0,
  connected: false,
  fps: 60,
  lastError: null,
  trackingStatus: null,
  trackingError: null,
  groundTrack: null,
  ui: {
    view: 'adaptive',
    selection: null,
    selectedFlowId: 'DEL-LON',
    dragging: null,
    tab: 'network',
    orbitMode: 'simulation',
  },

  setInit: (init) => set({ init }),
  setFrame: (frame) => {
    const current = get().latestFrame;
    set({
      prevFrame: current,
      latestFrame: frame,
      recvAt: performance.now(),
    });
  },
  setConnected: (connected) => set({ connected }),
  setFps: (fps) => set({ fps }),
  setError: (lastError) => set({ lastError }),
  setTrackingStatus: (trackingStatus) => set({ trackingStatus }),
  setTrackingError: (trackingError) => set({ trackingError }),
  setGroundTrack: (groundTrack) => set({ groundTrack }),
  setView: (view) => set((s) => ({ ui: { ...s.ui, view } })),
  setOrbitMode: (orbitMode) => set((s) => ({
    ui: { ...s.ui, orbitMode },
    groundTrack: null,
  })),
  setSelection: (selection) => set((s) => ({ ui: { ...s.ui, selection } })),
  setSelectedFlowId: (flowId) => set((s) => ({ ui: { ...s.ui, selectedFlowId: flowId } })),
  setDragging: (dragging) => set((s) => ({ ui: { ...s.ui, dragging } })),
  setTab: (tab) => set((s) => ({ ui: { ...s.ui, tab } })),
  sendCommand: (cmd, args = {}, id) => {
    socket.send({ type: 'cmd', cmd, args, id });
  },
}));

// Wire socket events into store automatically
socket.onStatus((connected) => {
  useSimStore.getState().setConnected(connected);
});

socket.onMessage((msg: ServerMessage) => {
  if (msg.type === 'init') {
    useSimStore.getState().setInit(msg);
  } else if (msg.type === 'frame') {
    useSimStore.getState().setFrame(msg);
  } else if (msg.type === 'error') {
    useSimStore.getState().setError(msg.msg ?? msg.error ?? 'The backend rejected a command.');
  }
});
