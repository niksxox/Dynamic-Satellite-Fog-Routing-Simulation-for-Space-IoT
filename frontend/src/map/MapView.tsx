import React, { useRef, useEffect, useState, useCallback } from 'react';
import DeckGL from '@deck.gl/react/typed';
import { MapView } from '@deck.gl/core/typed';
import { GeoJsonLayer, LineLayer, ScatterplotLayer, TextLayer, PathLayer } from '@deck.gl/layers/typed';
import { PathStyleExtension } from '@deck.gl/extensions/typed';
import * as topojson from 'topojson-client';
import countriesData from 'world-atlas/countries-110m.json';

import { useSimStore } from '../store/useSim';
import { satPositionsAt, InterpolatedSat } from './interpolate';
import { splitAntimeridianSegment, wrapLon } from '../lib/geo';

// Pre-convert countries topojson to GeoJSON once
const countriesGeoJson = (topojson.feature(
  countriesData as any,
  (countriesData as any).objects.countries
) as any);

const INITIAL_VIEW_STATE = {
  longitude: 10,
  latitude: 20,
  zoom: 1.3,
  minZoom: 1,
  maxZoom: 6,
  pitch: 0,
  bearing: 0,
};

interface DragState {
  isDragging: boolean;
  satId: number | null;
  dragCoord: [number, number] | null;
  startPos: [number, number] | null;
}

export const MapComponent: React.FC = () => {
  const deckRef = useRef<any>(null);
  const { latestFrame, init, ui, setSelection, setDragging, sendCommand, setFps } = useSimStore();

  const [interpolatedSats, setInterpolatedSats] = useState<InterpolatedSat[]>([]);
  const [dragState, setDragState] = useState<DragState>({
    isDragging: false,
    satId: null,
    dragCoord: null,
    startPos: null,
  });

  // FPS calculation
  const framesCountRef = useRef(0);
  const lastFpsTimeRef = useRef(performance.now());

  // 60 fps requestAnimationFrame loop for satellite positions
  useEffect(() => {
    let animId: number;

    const renderLoop = (now: number) => {
      // FPS measurement
      framesCountRef.current++;
      if (now - lastFpsTimeRef.current >= 1000) {
        setFps(framesCountRef.current);
        framesCountRef.current = 0;
        lastFpsTimeRef.current = now;
      }

      const store = useSimStore.getState();
      if (store.latestFrame) {
        const sats = satPositionsAt(store.latestFrame.sats, store.recvAt, now);
        setInterpolatedSats(sats);
      }
      animId = requestAnimationFrame(renderLoop);
    };

    animId = requestAnimationFrame(renderLoop);
    return () => cancelAnimationFrame(animId);
  }, [setFps]);

  // Coordinate lookup map
  const satCoordsMap = new Map<number, [number, number]>();
  for (const s of interpolatedSats) {
    if (dragState.isDragging && dragState.satId === s.id && dragState.dragCoord) {
      satCoordsMap.set(s.id, dragState.dragCoord);
    } else {
      satCoordsMap.set(s.id, [s.lon, s.lat]);
    }
  }

  const gsCoordsMap = new Map<number, [number, number]>();
  if (init?.ground) {
    for (const gs of init.ground) {
      gsCoordsMap.set(gs.id, [gs.lon, gs.lat]);
    }
  }

  const getNodeCoord = useCallback(
    (id: number): [number, number] | null => {
      if (id >= 120) {
        return gsCoordsMap.get(id) ?? null;
      }
      return satCoordsMap.get(id) ?? null;
    },
    [satCoordsMap, gsCoordsMap]
  );

  // Keyboard shortcut listeners (Space = pause/play, Esc = clear selection, F = fail item)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

      if (e.code === 'Space') {
        e.preventDefault();
        const frame = useSimStore.getState().latestFrame;
        sendCommand(frame?.running ? 'pause' : 'play');
      } else if (e.code === 'Escape') {
        setSelection(null);
      } else if (e.code === 'KeyF') {
        const sel = useSimStore.getState().ui.selection;
        if (sel?.type === 'link') {
          sendCommand('fail_link', { a: sel.a, b: sel.b });
        } else if (sel?.type === 'sat') {
          sendCommand('fail_sat', { id: sel.id });
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [sendCommand, setSelection]);

  // Dragging handlers per SPEC §13
  const handlePointerDown = (info: any, event: any) => {
    if (info && info.object && info.layer?.id === 'satellites') {
      const sat = info.object as InterpolatedSat;
      setDragState({
        isDragging: true,
        satId: sat.id,
        dragCoord: [sat.lon, sat.lat],
        startPos: [event.clientX, event.clientY],
      });
      setDragging(sat.id);
      // Disable deck controller panning synchronously
      if (deckRef.current?.deck) {
        deckRef.current.deck.setProps({
          controller: { dragPan: false, dragRotate: false },
        });
      }
    }
  };

  const handlePointerMove = (info: any, event: any) => {
    if (dragState.isDragging && dragState.satId !== null && deckRef.current?.deck) {
      const viewport = deckRef.current.deck.getViewports()[0];
      if (viewport) {
        const unproj = viewport.unproject([event.clientX, event.clientY]);
        if (unproj) {
          const lon = wrapLon(unproj[0]);
          const lat = Math.max(-85, Math.min(85, unproj[1]));
          setDragState((prev) => ({
            ...prev,
            dragCoord: [lon, lat],
          }));
        }
      }
    }
  };

  const handlePointerUp = () => {
    if (dragState.isDragging) {
      if (dragState.satId !== null && dragState.dragCoord) {
        sendCommand('move_sat', {
          id: dragState.satId,
          lat: dragState.dragCoord[1],
          lon: dragState.dragCoord[0],
        });
      }

      setDragState({
        isDragging: false,
        satId: null,
        dragCoord: null,
        startPos: null,
      });
      setDragging(null);

      // Restore controller
      if (deckRef.current?.deck) {
        deckRef.current.deck.setProps({
          controller: true,
        });
      }
    }
  };

  // Build layers
  const layers: any[] = [];

  // 1. Land GeoJson
  layers.push(
    new GeoJsonLayer({
      id: 'countries',
      data: countriesGeoJson,
      filled: true,
      stroked: true,
      getFillColor: [18, 40, 77, 255],      // #12284d
      getLineColor: [36, 66, 110, 255],     // #24426e
      lineWidthMinPixels: 0.5,
      wrapLongitude: true,
      pickable: false,
    })
  );

  // 2. ISL & GSL Links (Split across antimeridian)
  if (latestFrame?.links) {
    const linkSegments: any[] = [];

    for (const link of latestFrame.links) {
      const c1 = getNodeCoord(link.a);
      const c2 = getNodeCoord(link.b);
      if (!c1 || !c2) continue;

      const splits = splitAntimeridianSegment(c1, c2);
      for (const seg of splits) {
        linkSegments.push({
          source: seg[0],
          target: seg[1],
          k: link.k,
          up: link.up,
          rho: link.rho,
          ms: link.ms,
          a: link.a,
          b: link.b,
        });
      }
    }

    layers.push(
      new LineLayer({
        id: 'links',
        data: linkSegments,
        getSourcePosition: (d: any) => d.source,
        getTargetPosition: (d: any) => d.target,
        getColor: (d: any) => {
          if (d.up === 0) return [229, 72, 77, 120]; // down crit red
          if (d.rho > 0.85) return [229, 72, 77, 180]; // high congestion
          if (d.rho > 0.5) return [245, 185, 66, 160]; // medium amber
          return [79, 195, 217, 140]; // teal
        },
        getWidth: (d: any) => (d.k === 1 ? 1.5 : 1.0),
        widthMinPixels: 1,
        pickable: true,
        autoHighlight: true,
        highlightColor: [255, 255, 255, 150],
        onClick: (info: any) => {
          if (info.object) {
            setSelection({ type: 'link', a: info.object.a, b: info.object.b });
          }
        },
        updateTriggers: {
          getSourcePosition: [interpolatedSats, dragState.dragCoord],
          getTargetPosition: [interpolatedSats, dragState.dragCoord],
        },
      })
    );
  }

  // 3. Selected Flow Paths (Adaptive: teal solid; Static: orange dashed)
  if (latestFrame?.flows && ui.selectedFlowId) {
    const currentFlow = latestFrame.flows.find((f) => f.id === ui.selectedFlowId);
    if (currentFlow) {
      // Static Path Overlay
      if (ui.view !== 'adaptive') {
        const staticPaths: any[] = [];
        for (const chunk of currentFlow.static.paths) {
          for (let i = 0; i < chunk.nodes.length - 1; i++) {
            const c1 = getNodeCoord(chunk.nodes[i]);
            const c2 = getNodeCoord(chunk.nodes[i + 1]);
            if (c1 && c2) {
              const splits = splitAntimeridianSegment(c1, c2);
              for (const seg of splits) {
                staticPaths.push({
                  path: seg,
                  blackholed: currentFlow.static.blackholed,
                });
              }
            }
          }
        }

        layers.push(
          new PathLayer({
            id: 'static-paths',
            data: staticPaths,
            getPath: (d: any) => d.path,
            getColor: (d: any) => (d.blackholed ? [229, 72, 77, 220] : [232, 132, 58, 220]),
            getWidth: 3,
            widthMinPixels: 2.5,
            dashJustified: true,
            getDashArray: [6, 4],
            extensions: [new PathStyleExtension({ dash: true })],
            updateTriggers: {
              getPath: [interpolatedSats, dragState.dragCoord],
            },
          })
        );
      }

      // Adaptive Path Overlay
      if (ui.view !== 'static') {
        const adaptivePaths: any[] = [];
        for (const chunk of currentFlow.adaptive.paths) {
          for (let i = 0; i < chunk.nodes.length - 1; i++) {
            const c1 = getNodeCoord(chunk.nodes[i]);
            const c2 = getNodeCoord(chunk.nodes[i + 1]);
            if (c1 && c2) {
              const splits = splitAntimeridianSegment(c1, c2);
              for (const seg of splits) {
                adaptivePaths.push({
                  path: seg,
                  blackholed: currentFlow.adaptive.blackholed,
                });
              }
            }
          }
        }

        layers.push(
          new PathLayer({
            id: 'adaptive-paths',
            data: adaptivePaths,
            getPath: (d: any) => d.path,
            getColor: (d: any) => (d.blackholed ? [229, 72, 77, 240] : [79, 195, 217, 240]),
            getWidth: 4,
            widthMinPixels: 3.5,
            updateTriggers: {
              getPath: [interpolatedSats, dragState.dragCoord],
            },
          })
        );
      }
    }
  }

  // 4. Ground Stations (Scatterplot + TextLayer)
  if (init?.ground) {
    layers.push(
      new ScatterplotLayer({
        id: 'ground-stations',
        data: init.ground,
        getPosition: (d: any) => [d.lon, d.lat],
        getFillColor: [232, 132, 58, 240], // orange
        getRadius: 24000,
        radiusMinPixels: 5,
        radiusMaxPixels: 9,
        pickable: true,
        onClick: (info: any) => {
          if (info.object) {
            setSelection({ type: 'gs', id: info.object.id });
          }
        },
      })
    );

    layers.push(
      new TextLayer({
        id: 'ground-station-labels',
        data: init.ground,
        getPosition: (d: any) => [d.lon, d.lat],
        getText: (d: any) => d.name,
        getSize: 11,
        getColor: [230, 238, 248, 220],
        getTextAnchor: 'start',
        getAlignmentBaseline: 'center',
        getPixelOffset: [10, 0],
        fontFamily: 'Inter, sans-serif',
      })
    );
  }

  // 5. Satellites (ScatterplotLayer with teal halo)
  layers.push(
    new ScatterplotLayer({
      id: 'satellites-halo',
      data: interpolatedSats,
      getPosition: (d: InterpolatedSat) => {
        if (dragState.isDragging && dragState.satId === d.id && dragState.dragCoord) {
          return [dragState.dragCoord[0], dragState.dragCoord[1]];
        }
        return [d.lon, d.lat];
      },
      getFillColor: (d: InterpolatedSat) =>
        d.st === 1 ? [229, 72, 77, 90] : [79, 195, 217, 70],
      getRadius: 35000,
      radiusMinPixels: 6,
      radiusMaxPixels: 12,
      pickable: false,
      updateTriggers: {
        getPosition: [interpolatedSats, dragState.dragCoord],
      },
    })
  );

  layers.push(
    new ScatterplotLayer({
      id: 'satellites',
      data: interpolatedSats,
      getPosition: (d: InterpolatedSat) => {
        if (dragState.isDragging && dragState.satId === d.id && dragState.dragCoord) {
          return [dragState.dragCoord[0], dragState.dragCoord[1]];
        }
        return [d.lon, d.lat];
      },
      getFillColor: (d: InterpolatedSat) =>
        d.st === 1 ? [229, 72, 77, 240] : [255, 255, 255, 255],
      getRadius: 18000,
      radiusMinPixels: 3.5,
      radiusMaxPixels: 6,
      pickable: true,
      autoHighlight: true,
      highlightColor: [79, 195, 217, 200],
      onClick: (info: any) => {
        if (!dragState.isDragging && info.object) {
          setSelection({ type: 'sat', id: info.object.id });
        }
      },
      updateTriggers: {
        getPosition: [interpolatedSats, dragState.dragCoord],
      },
    })
  );

  return (
    <div
      className="relative flex-1 h-full w-full bg-[#0A1428] overflow-hidden cursor-grab active:cursor-grabbing"
      onPointerDown={(e) => {
        if (deckRef.current?.deck) {
          const info = deckRef.current.deck.pickObject({
            x: e.clientX,
            y: e.clientY,
            radius: 8,
          });
          handlePointerDown(info, e);
        }
      }}
      onPointerMove={(e) => {
        if (dragState.isDragging) {
          handlePointerMove(null, e);
        }
      }}
      onPointerUp={handlePointerUp}
    >
      <DeckGL
        ref={deckRef}
        views={new MapView({ repeat: true })}
        initialViewState={INITIAL_VIEW_STATE}
        controller={true}
        layers={layers}
        getTooltip={({ object, layer }: any) => {
          if (!object || !layer) return null;
          if (layer.id === 'satellites') {
            return {
              html: `<div style="font-family:Inter; font-size:11px; padding:4px 8px; background:#0F1E3A; border:1px solid #1E3558; border-radius:6px; color:#E6EEF8;">
                <strong>Satellite S${String(object.id).padStart(3, '0')}</strong><br/>
                Lat: ${object.lat.toFixed(2)}° | Lon: ${object.lon.toFixed(2)}°<br/>
                Status: ${object.st === 1 ? '<span style="color:#E5484D">Failed</span>' : '<span style="color:#3DD68C">Nominal</span>'}
              </div>`,
            };
          }
          if (layer.id === 'ground-stations') {
            return {
              html: `<div style="font-family:Inter; font-size:11px; padding:4px 8px; background:#0F1E3A; border:1px solid #1E3558; border-radius:6px; color:#E6EEF8;">
                <strong>${object.name} OGS</strong><br/>
                Coord: ${object.lat.toFixed(2)}°, ${object.lon.toFixed(2)}°
              </div>`,
            };
          }
          if (layer.id === 'links') {
            return {
              html: `<div style="font-family:Inter; font-size:11px; padding:4px 8px; background:#0F1E3A; border:1px solid #1E3558; border-radius:6px; color:#E6EEF8;">
                <strong>${object.k === 1 ? 'Ground Link (GSL)' : 'Inter-Sat Link (ISL)'}</strong><br/>
                Nodes: ${object.a} ↔ ${object.b}<br/>
                Utilisation: ${(object.rho * 100).toFixed(0)}% | Latency: ${object.ms.toFixed(1)} ms
              </div>`,
            };
          }
          return null;
        }}
      />

      {/* Visual ring feedback while dragging */}
      {dragState.isDragging && dragState.dragCoord && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 bg-panel2/90 border border-teal-bright px-3 py-1 rounded-full text-xs font-mono text-teal-bright shadow-lg pointer-events-none">
          Dragging Satellite S{String(dragState.satId).padStart(3, '0')} → Drop to re-phase orbit
        </div>
      )}
    </div>
  );
};
