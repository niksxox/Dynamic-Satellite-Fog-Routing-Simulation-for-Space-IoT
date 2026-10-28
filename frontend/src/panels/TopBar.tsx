import React from 'react';
import { useSimStore } from '../store/useSim';
import { Radio, Play, Pause, RotateCcw, FastForward, Sliders } from 'lucide-react';
import { formatSimClock } from '../lib/format';

export const TopBar: React.FC = () => {
  const { connected, latestFrame, ui, setView, setTab, sendCommand } = useSimStore();
  const running = latestFrame?.running ?? true;
  const timeSim = latestFrame?.t ?? 0;
  const scale = latestFrame?.scale ?? 20;

  return (
    <header className="h-14 border-b border-border bg-panel px-4 flex items-center justify-between select-none z-20 shrink-0">
      {/* Brand & Tabs */}
      <div className="flex items-center space-x-6">
        <div className="flex items-center space-x-2.5">
          <div className="w-8 h-8 rounded-lg bg-navy flex items-center justify-center border border-border shadow-inner">
            <Radio className="w-4 h-4 text-teal-bright animate-pulse" />
          </div>
          <div>
            <h1 className="text-sm font-bold tracking-tight text-text flex items-center gap-2">
              SatRoute
              <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-panel2 border border-border text-teal-bright font-normal">
                Autonomous LEO Mesh
              </span>
            </h1>
          </div>
        </div>

        {/* Navigation Tabs */}
        <nav className="flex items-center space-x-1 bg-panel2/60 p-1 rounded-lg border border-border/60">
          {(['network', 'controls', 'performance', 'logs'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1 text-xs font-medium rounded-md transition-colors capitalize ${
                ui.tab === t
                  ? 'bg-panel border border-border text-teal-bright shadow-sm'
                  : 'text-muted hover:text-text hover:bg-white/5'
              }`}
            >
              {t === 'network' ? 'Network View' : t}
            </button>
          ))}
        </nav>
      </div>

      {/* Middle Sim Clock & Controls */}
      <div className="flex items-center space-x-3 bg-panel2/80 px-3 py-1 rounded-lg border border-border text-xs font-mono">
        <span className="text-teal-bright font-bold tracking-wider">
          {formatSimClock(timeSim)}
        </span>
        <span className="text-muted text-[10px]">({scale}x)</span>
        <div className="h-3 w-px bg-border mx-1" />
        <button
          onClick={() => sendCommand(running ? 'pause' : 'play')}
          className="p-1 rounded hover:bg-white/10 text-muted hover:text-text transition"
          title={running ? 'Pause (Space)' : 'Play (Space)'}
        >
          {running ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5 text-ok" />}
        </button>
        <button
          onClick={() => sendCommand('reset')}
          className="p-1 rounded hover:bg-white/10 text-muted hover:text-text transition"
          title="Reset Simulation"
        >
          <RotateCcw className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Right: View Toggle & Status */}
      <div className="flex items-center space-x-4">
        {/* Algorithm View Toggle */}
        <div className="flex items-center bg-panel2 p-0.5 rounded-lg border border-border text-xs">
          <button
            onClick={() => setView('adaptive')}
            className={`px-2.5 py-1 rounded-md transition font-medium ${
              ui.view === 'adaptive'
                ? 'bg-teal-bright/20 text-teal-bright font-semibold'
                : 'text-muted hover:text-text'
            }`}
          >
            Adaptive
          </button>
          <button
            onClick={() => setView('static')}
            className={`px-2.5 py-1 rounded-md transition font-medium ${
              ui.view === 'static'
                ? 'bg-orange/20 text-orange font-semibold'
                : 'text-muted hover:text-text'
            }`}
          >
            Static
          </button>
          <button
            onClick={() => setView('compare')}
            className={`px-2.5 py-1 rounded-md transition font-medium ${
              ui.view === 'compare'
                ? 'bg-white/10 text-text font-semibold border border-white/20'
                : 'text-muted hover:text-text'
            }`}
          >
            Compare
          </button>
        </div>

        {/* Status Pill */}
        <div
          className={`flex items-center space-x-2 px-2.5 py-1 rounded-full text-xs font-medium border ${
            connected
              ? 'bg-ok/10 text-ok border-ok/30'
              : 'bg-crit/10 text-crit border-crit/30'
          }`}
        >
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              connected ? 'bg-ok animate-pulse' : 'bg-crit'
            }`}
          />
          <span>{connected ? 'Live' : 'Offline'}</span>
        </div>
      </div>
    </header>
  );
};
