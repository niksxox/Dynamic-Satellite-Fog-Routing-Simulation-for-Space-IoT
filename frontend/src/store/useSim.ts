import { create } from 'zustand';
import { InitMessage, FrameMessage, ClientCommand } from '../net/types';
import { socket } from '../net/socket';

export type ViewMode = 'adaptive' | 'static' | 'compare';

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
}

interface SimStore {
  init: InitMessage | null;
  latestFrame: FrameMessage | null;
  prevFrame: FrameMessage | null;
  recvAt: number;
  connected: boolean;
  fps: number;
  ui: UIState;

  // Actions
  setInit: (init: InitMessage) => void;
  setFrame: (frame: FrameMessage) => void;
  setConnected: (connected: boolean) => void;
  setFps: (fps: number) => void;
  setView: (view: ViewMode) => void;
  setSelection: (selection: SelectionType) => void;
  setSelectedFlowId: (flowId: string | null) => void;
  setDragging: (id: number | null) => void;
  setTab: (tab: 'network' | 'controls' | 'performance' | 'logs') => void;
  sendCommand: (cmd: ClientCommand['cmd'], args?: Record<string, any>, id?: string) => void;
}

export const useSimStore = create<SimStore>((set, get) => ({
  init: null,
  latestFrame: null,
  prevFrame: null,
  recvAt: 0,
  connected: false,
  fps: 60,
  ui: {
    view: 'adaptive',
    selection: null,
    selectedFlowId: 'DEL->LON',
    dragging: null,
    tab: 'network',
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
  setView: (view) => set((s) => ({ ui: { ...s.ui, view } })),
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

socket.onMessage((msg) => {
  if (msg.type === 'init') {
    useSimStore.getState().setInit(msg as InitMessage);
  } else if (msg.type === 'frame') {
    useSimStore.getState().setFrame(msg as FrameMessage);
  }
});
