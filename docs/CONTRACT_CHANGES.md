v1 contract frozen

## Differences and Confirmations (Engine Implementation vs SPEC Section 12)

1. **`Init.config` dictionary**:
   - The engine produces `config` with keys `{"num_sats": int, "time_scale": float, "cadence_ticks": int}`.
   - Handled via `SimConfig` with `extra="allow"` to support loose/extensible configuration dictionaries.

2. **Link state (`links[].up`)**:
   - Represented as integer `1` (link operational) or `0` (link down) in `Engine.step()` output.
   - `LinkOut.up` model specifies `int` (1 / 0).

3. **Satellite status (`sats[].st`)**:
   - Represented as integer `0` (operational) or `1` (failed node) in `Engine.step()` output.
   - `SatOut.st` model specifies `int` (0 / 1).

4. **Flow structure (`flows[]`)**:
   - Each entry has `id: str`, `adaptive: FlowEval`, and `static: FlowEval`.
   - Each `FlowEval` contains `paths` (list of `{"nodes": list[int], "mbps": float}`), `ms: float`, `pdr: float`, and `blackholed: bool`.

5. **Client Commands & Responses**:
   - Command models extend `BaseCmd` supporting optional request tracking `id` and `type` tag.
   - All client commands (`play`, `pause`, `reset`, `set_scale`, `set_weights`, `set_params`, `fail_link`, `restore_link`, `fail_sat`, `restore_sat`, `move_sat`, `move_gs`, `preview_orbit`, `set_flow_scale`, `add_flow`, `remove_flow`) are strictly validated using `parse_command()`.
   - `preview_orbit` command response produces `{"type": "orbit_preview", "id": id, "track": [[lon, lat], ...]}`.
   - Acknowledgment and error message models (`Ack`, `ErrorMsg`) allow both `id` and descriptive messages (`msg` or `error`).

6. **Live metric units**:
   - Frame `metrics.adaptive.pdr`, `metrics.static.pdr`, and `metrics.linkUptime` are ratios from 0 to 1, formatted as percentages by the frontend.
   - Headless summary snapshots retain percentage values for reporting.

7. **Read-only TLE tracking**:
   - Live frames may include `positionSource: "tle"` when satellite positions and topology are driven by public CelesTrak GP TLEs or the alternate `tle.ivanstanojevic.me` TLE API propagated with SGP4; the field is optional for older frames.
   - `GET /api/tracking` reports source, TLE age, refresh status, and tracked NORAD IDs. `GET /api/tracking/{satellite_index}/ground-track` returns a predicted single-orbit ground track.
   - Routes, failures, and metrics remain model-generated and are not operational telemetry.
