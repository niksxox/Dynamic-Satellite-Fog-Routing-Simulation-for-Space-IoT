import React, { useState } from 'react';
import { useSimStore } from '../store/useSim';
import { Play, Pause, RotateCcw, Zap, AlertTriangle, ShieldCheck, RefreshCw, Sliders } from 'lucide-react';

export const Controls: React.FC = () => {
  const { latestFrame, sendCommand } = useSimStore();
  const [isOpen, setIsOpen] = useState(false);
  const [weights, setWeights] = useState({ a: 1.0, b: 1.0, c: 1.0 });
  const [flowScale, setFlowScale] = useState(1.0);
  const [speed, setSpeed] = useState(20);

  const running = latestFrame?.running ?? true;

  const handleWeightChange = (key: 'a' | 'b' | 'c', val: number) => {
    const next = { ...weights, [key]: val };
    setWeights(next);
    sendCommand('set_weights', next);
  };

  const handleSpeedChange = (val: number) => {
    setSpeed(val);
    sendCommand('set_scale', { scale: val });
  };

  const handleFlashCrowd = () => {
    const next = flowScale === 1.0 ? 3.0 : 1.0;
    setFlowScale(next);
    sendCommand('set_flow_scale', { factor: next });
  };

  const handleBreakActiveLink = () => {
    if (!latestFrame) return;
    const upLinks = latestFrame.links.filter((l) => l.up === 1 && l.k === 0);
    if (upLinks.length > 0) {
      const target = upLinks[Math.floor(Math.random() * upLinks.length)];
      sendCommand('fail_link', { a: target.a, b: target.b });
    }
  };

  const handleBreakSatellite = () => {
    if (!latestFrame) return;
    const upSats = latestFrame.sats.filter((s) => s.st === 0);
    if (upSats.length > 0) {
      const target = upSats[Math.floor(Math.random() * upSats.length)];
      sendCommand('fail_sat', { id: target.id });
    }
  };

  const handleRestoreAll = () => {
    sendCommand('reset');
  };

  return (
    <div
      className={`absolute top-18 left-4 z-20 transition-all duration-300 ${
        isOpen ? 'w-72' : 'w-10'
      }`}
    >
      <div className="bg-panel/95 backdrop-blur-md rounded-xl border border-border shadow-2xl glow-panel overflow-hidden">
        {/* Toggle Header */}
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="w-full h-10 px-3 flex items-center justify-between text-xs font-semibold text-text hover:bg-white/5 transition"
        >
          <div className="flex items-center space-x-2">
            <Sliders className="w-4 h-4 text-teal-bright" />
            {isOpen && <span>Simulator Controls</span>}
          </div>
          {isOpen && <span className="text-[10px] text-muted">Collapse ◄</span>}
        </button>

        {isOpen && (
          <div className="p-4 space-y-4 border-t border-border text-xs max-h-[calc(100vh-140px)] overflow-y-auto">
            {/* Speed Slider */}
            <div>
              <div className="flex justify-between text-muted mb-1 font-mono text-[11px]">
                <span>Time Scale (Speed):</span>
                <span className="text-teal-bright font-bold">{speed}x</span>
              </div>
              <input
                type="range"
                min="1"
                max="120"
                value={speed}
                onChange={(e) => handleSpeedChange(Number(e.target.value))}
                className="w-full accent-teal-bright h-1.5 bg-panel2 rounded-lg cursor-pointer"
              />
            </div>

            {/* Quick Actions */}
            <div className="space-y-2 pt-2 border-t border-border">
              <span className="text-muted text-[10px] uppercase font-bold tracking-wider">
                Chaos Injection
              </span>

              <button
                onClick={handleBreakActiveLink}
                className="w-full flex items-center justify-center space-x-2 py-2 px-3 rounded-lg bg-crit/10 border border-crit/30 text-crit font-semibold hover:bg-crit/20 transition"
              >
                <AlertTriangle className="w-3.5 h-3.5" />
                <span>Break Random Active Link</span>
              </button>

              <button
                onClick={handleBreakSatellite}
                className="w-full flex items-center justify-center space-x-2 py-2 px-3 rounded-lg bg-orange/10 border border-orange/30 text-orange font-semibold hover:bg-orange/20 transition"
              >
                <Zap className="w-3.5 h-3.5" />
                <span>Break Random Satellite</span>
              </button>

              <button
                onClick={handleFlashCrowd}
                className={`w-full flex items-center justify-center space-x-2 py-2 px-3 rounded-lg border font-semibold transition ${
                  flowScale > 1
                    ? 'bg-warn text-bg border-warn'
                    : 'bg-warn/10 border-warn/30 text-warn hover:bg-warn/20'
                }`}
              >
                <span>{flowScale > 1 ? '⚡ Flash Crowd 3x (ACTIVE)' : 'Flash Crowd 3x'}</span>
              </button>

              <button
                onClick={handleRestoreAll}
                className="w-full flex items-center justify-center space-x-2 py-2 px-3 rounded-lg bg-ok/10 border border-ok/30 text-ok font-semibold hover:bg-ok/20 transition"
              >
                <ShieldCheck className="w-3.5 h-3.5" />
                <span>Restore All & Reset</span>
              </button>
            </div>

            {/* Cost Weights a, b, c */}
            <div className="space-y-3 pt-3 border-t border-border">
              <span className="text-muted text-[10px] uppercase font-bold tracking-wider">
                Cost Weights (Adaptive)
              </span>

              <div>
                <div className="flex justify-between text-muted text-[11px] mb-0.5">
                  <span>α (Latency weight):</span>
                  <span className="text-text font-mono">{weights.a.toFixed(1)}</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="3"
                  step="0.1"
                  value={weights.a}
                  onChange={(e) => handleWeightChange('a', Number(e.target.value))}
                  className="w-full accent-teal-bright h-1 bg-panel2 rounded cursor-pointer"
                />
              </div>

              <div>
                <div className="flex justify-between text-muted text-[11px] mb-0.5">
                  <span>β (Congestion weight):</span>
                  <span className="text-text font-mono">{weights.b.toFixed(1)}</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="3"
                  step="0.1"
                  value={weights.b}
                  onChange={(e) => handleWeightChange('b', Number(e.target.value))}
                  className="w-full accent-teal-bright h-1 bg-panel2 rounded cursor-pointer"
                />
              </div>

              <div>
                <div className="flex justify-between text-muted text-[11px] mb-0.5">
                  <span>γ (Risk weight):</span>
                  <span className="text-text font-mono">{weights.c.toFixed(1)}</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="3"
                  step="0.1"
                  value={weights.c}
                  onChange={(e) => handleWeightChange('c', Number(e.target.value))}
                  className="w-full accent-teal-bright h-1 bg-panel2 rounded cursor-pointer"
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
