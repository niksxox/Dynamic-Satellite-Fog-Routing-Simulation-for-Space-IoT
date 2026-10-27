import React from 'react';
import { useSimStore } from '../store/useSim';
import { X, AlertTriangle, CheckCircle, Radio, Wifi, Zap } from 'lucide-react';
import { formatNumber } from '../lib/format';

export const Inspector: React.FC = () => {
  const { ui, latestFrame, init, trackingStatus, setSelection, sendCommand } = useSimStore();
  const selection = ui.selection;

  if (!selection || !latestFrame) return null;

  const handleClose = () => setSelection(null);

  if (selection.type === 'sat') {
    const sat = latestFrame.sats.find((s) => s.id === selection.id);
    const trackedSat = trackingStatus?.satellites.find((tracked) => tracked.id === selection.id);
    const plane = init?.planes[selection.id] ?? Math.floor(selection.id / 10);
    const isFailed = sat?.st === 1;
    const isLiveTracking = ui.orbitMode === 'live' && latestFrame.positionSource === 'tle';

    return (
      <div className="absolute bottom-6 right-6 w-80 bg-panel/95 backdrop-blur-md rounded-xl border border-border shadow-2xl p-4 z-30 glow-panel text-xs animate-in fade-in slide-in-from-bottom-2 duration-200">
        <div className="flex items-center justify-between pb-3 mb-3 border-b border-border">
          <div className="flex items-center space-x-2">
            <div className="w-6 h-6 rounded bg-navy flex items-center justify-center border border-border">
              <Radio className="w-3.5 h-3.5 text-teal-bright" />
            </div>
            <div>
              <div className="font-semibold text-text">
                {trackedSat?.name ?? `Satellite S${String(selection.id).padStart(3, '0')}`}
              </div>
              <div className="text-[10px] text-muted font-mono">
                {trackedSat ? `NORAD ${trackedSat.norad_id}` : `Plane #${plane}`}
              </div>
            </div>
          </div>
          <button onClick={handleClose} className="text-muted hover:text-text p-1">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-2 mb-4 font-mono text-[11px]">
          <div className="flex justify-between">
            <span className="text-muted">Status:</span>
            <span className={isFailed ? 'text-crit font-bold' : 'text-ok font-semibold'}>
              {isFailed ? 'FAILED (Offline)' : 'NOMINAL (Operational)'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted">Latitude:</span>
            <span className="text-text tabular-nums">{sat ? formatNumber(sat.lat, 3) : '--'}°</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted">Longitude:</span>
            <span className="text-text tabular-nums">{sat ? formatNumber(sat.lon, 3) : '--'}°</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted">Altitude:</span>
            <span className="text-text tabular-nums">{sat?.alt ?? 550} km</span>
          </div>
          {isLiveTracking && (
            <div className="text-teal-bright">Position estimated from published orbital elements.</div>
          )}
        </div>

        {!isLiveTracking && <div className="flex gap-2">
          {isFailed ? (
            <button
              onClick={() => sendCommand('restore_sat', { id: selection.id })}
              className="flex-1 py-1.5 px-3 rounded-lg bg-ok/20 text-ok border border-ok/40 font-semibold hover:bg-ok/30 transition text-center"
            >
              Restore Satellite
            </button>
          ) : (
            <button
              onClick={() => sendCommand('fail_sat', { id: selection.id })}
              className="flex-1 py-1.5 px-3 rounded-lg bg-crit/20 text-crit border border-crit/40 font-semibold hover:bg-crit/30 transition text-center"
            >
              Fail Satellite (F)
            </button>
          )}
        </div>}
      </div>
    );
  }

  if (selection.type === 'gs') {
    const gs = init?.ground.find((g) => g.id === selection.id);
    return (
      <div className="absolute bottom-6 right-6 w-80 bg-panel/95 backdrop-blur-md rounded-xl border border-border shadow-2xl p-4 z-30 glow-panel text-xs animate-in fade-in slide-in-from-bottom-2 duration-200">
        <div className="flex items-center justify-between pb-3 mb-3 border-b border-border">
          <div className="flex items-center space-x-2">
            <div className="w-6 h-6 rounded bg-navy flex items-center justify-center border border-border">
              <Zap className="w-3.5 h-3.5 text-orange" />
            </div>
            <div>
              <div className="font-semibold text-text">{gs?.name ?? 'Ground Station'}</div>
              <div className="text-[10px] text-muted font-mono">Node ID #{selection.id}</div>
            </div>
          </div>
          <button onClick={handleClose} className="text-muted hover:text-text p-1">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-2 mb-4 font-mono text-[11px]">
          <div className="flex justify-between">
            <span className="text-muted">Type:</span>
            <span className="text-orange font-semibold">Optical Ground Station (OGS)</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted">Coordinates:</span>
            <span className="text-text tabular-nums">{gs ? `${gs.lat.toFixed(2)}°, ${gs.lon.toFixed(2)}°` : '--'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted">Min Elevation:</span>
            <span className="text-text">25.0° (GSL threshold)</span>
          </div>
        </div>
      </div>
    );
  }

  if (selection.type === 'link') {
    const link = latestFrame.links.find(
      (l) => (l.a === selection.a && l.b === selection.b) || (l.a === selection.b && l.b === selection.a)
    );
    const isUp = link?.up === 1;
    const isGSL = link?.k === 1;

    return (
      <div className="absolute bottom-6 right-6 w-80 bg-panel/95 backdrop-blur-md rounded-xl border border-border shadow-2xl p-4 z-30 glow-panel text-xs animate-in fade-in slide-in-from-bottom-2 duration-200">
        <div className="flex items-center justify-between pb-3 mb-3 border-b border-border">
          <div className="flex items-center space-x-2">
            <div className="w-6 h-6 rounded bg-navy flex items-center justify-center border border-border">
              <Wifi className="w-3.5 h-3.5 text-teal-bright" />
            </div>
            <div>
              <div className="font-semibold text-text">
                {isGSL ? 'GSL Link' : 'ISL Laser Link'}
              </div>
              <div className="text-[10px] text-muted font-mono">
                Nodes {selection.a} ↔ {selection.b}
              </div>
            </div>
          </div>
          <button onClick={handleClose} className="text-muted hover:text-text p-1">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="space-y-2 mb-4 font-mono text-[11px]">
          <div className="flex justify-between">
            <span className="text-muted">Link State:</span>
            <span className={isUp ? 'text-ok font-semibold' : 'text-crit font-bold'}>
              {isUp ? 'UP (Active)' : 'DOWN (Failed)'}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted">Utilisation (ρ):</span>
            <span className="text-text tabular-nums">{link ? `${(link.rho * 100).toFixed(1)}%` : '--'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted">Latency:</span>
            <span className="text-text tabular-nums">{link ? `${link.ms.toFixed(1)} ms` : '--'}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted">Capacity:</span>
            <span className="text-text">{isGSL ? '1000 Mbps' : '2000 Mbps'}</span>
          </div>
        </div>

        <div className="flex gap-2">
          {isUp ? (
            <button
              onClick={() => sendCommand('fail_link', { a: selection.a, b: selection.b })}
              className="flex-1 py-1.5 px-3 rounded-lg bg-crit/20 text-crit border border-crit/40 font-semibold hover:bg-crit/30 transition text-center"
            >
              Fail Link (F)
            </button>
          ) : (
            <button
              onClick={() => sendCommand('restore_link', { a: selection.a, b: selection.b })}
              className="flex-1 py-1.5 px-3 rounded-lg bg-ok/20 text-ok border border-ok/40 font-semibold hover:bg-ok/30 transition text-center"
            >
              Restore Link
            </button>
          )}
        </div>
      </div>
    );
  }

  return null;
};
