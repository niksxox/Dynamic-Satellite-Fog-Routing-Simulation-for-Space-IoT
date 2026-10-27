import React from 'react';
import { useSimStore } from '../store/useSim';
import { CheckCircle2, AlertTriangle, AlertOctagon, X } from 'lucide-react';

export const FooterBar: React.FC = () => {
  const { latestFrame, fps, lastError, setError } = useSimStore();
  const activeFailures = latestFrame?.metrics.activeFailures ?? 0;
  const pdr = latestFrame?.metrics.adaptive.pdr ?? 1.0;
  const events = latestFrame?.events ?? [];

  const isNominal = activeFailures === 0 && pdr >= 0.95;
  const isWarn = activeFailures > 0 || (pdr < 0.95 && pdr >= 0.8);

  return (
    <footer className="h-9 border-t border-border bg-panel px-4 flex items-center justify-between text-xs select-none shrink-0 z-20">
      {/* Legend */}
      <div className="flex items-center space-x-5 text-[11px]">
        <div className="flex items-center space-x-1.5">
          <span className="w-3 h-1 rounded-full bg-teal-bright" />
          <span className="text-muted">Adaptive Path</span>
        </div>
        <div className="flex items-center space-x-1.5">
          <span className="w-3 h-1 rounded-full bg-orange" />
          <span className="text-muted">Static Path</span>
        </div>
        <div className="flex items-center space-x-1.5">
          <span className="w-2 h-2 rounded-full bg-white border border-teal-bright" />
          <span className="text-muted">Satellite</span>
        </div>
        <div className="flex items-center space-x-1.5">
          <span className="w-2 h-2 rounded-full bg-orange" />
          <span className="text-muted">Ground Station</span>
        </div>
      </div>

      {/* Center Event Toast Feed */}
      <div className="flex-1 max-w-md mx-4 overflow-hidden text-center">
        {lastError ? (
          <span className="flex items-center justify-center gap-2 font-mono text-[11px] text-crit truncate">
            <span>{lastError}</span>
            <button onClick={() => setError(null)} aria-label="Dismiss error">
              <X className="w-3 h-3" />
            </button>
          </span>
        ) : events.length > 0 ? (
          <span className="font-mono text-[11px] text-teal-bright animate-pulse truncate block">
            [{events[events.length - 1].kind.toUpperCase()}] {events[events.length - 1].msg}
          </span>
        ) : null}
      </div>

      {/* System Status & FPS */}
      <div className="flex items-center space-x-4">
        <div className="flex items-center space-x-1.5">
          {isNominal ? (
            <>
              <CheckCircle2 className="w-3.5 h-3.5 text-ok" />
              <span className="text-ok font-semibold text-[11px]">All Systems Nominal</span>
            </>
          ) : isWarn ? (
            <>
              <AlertTriangle className="w-3.5 h-3.5 text-warn" />
              <span className="text-warn font-semibold text-[11px]">Degraded / Active Outage</span>
            </>
          ) : (
            <>
              <AlertOctagon className="w-3.5 h-3.5 text-crit" />
              <span className="text-crit font-semibold text-[11px]">Severe Disruption</span>
            </>
          )}
        </div>

        <div className="text-[10px] font-mono text-muted pl-2 border-l border-border">
          {fps} FPS
        </div>
      </div>
    </footer>
  );
};
