import React from 'react';
import { TopBar } from './panels/TopBar';
import { MapComponent } from './map/MapView';
import { LiveMetrics } from './panels/LiveMetrics';
import { Controls } from './panels/Controls';
import { Inspector } from './panels/Inspector';
import { FooterBar } from './panels/FooterBar';

export default function App() {
  return (
    <div className="flex flex-col h-screen w-screen bg-bg text-text overflow-hidden select-none">
      {/* 1. Header Navigation Bar */}
      <TopBar />

      {/* 2. Main Simulation Workspace */}
      <div className="flex-1 relative flex overflow-hidden">
        {/* Interactive Left Controls Drawer */}
        <Controls />

        {/* 2D Deck.gl Live Satellite Mesh Map */}
        <MapComponent />

        {/* Real-time Telemetry & Metrics Dashboard */}
        <LiveMetrics />

        {/* Click-to-Inspect Overlay Card */}
        <Inspector />
      </div>

      {/* 3. Status & Diagnostic Footer */}
      <FooterBar />
    </div>
  );
}
