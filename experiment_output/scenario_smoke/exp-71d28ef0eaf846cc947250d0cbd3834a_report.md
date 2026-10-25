# Experiment exp-71d28ef0eaf846cc947250d0cbd3834a

Scenario: `normal_satellite_mobility` — Slow deterministic circular satellite motion.
Status: **completed**; storage: `local_export_only`; elapsed: 0.032s

| Scenario | Algorithm | Successful / failed | Mean latency (ms) | PDR | Throughput (Mbps) | Recovery (ms) | Reroutes | Latency 95% CI |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| normal_satellite_mobility | multi_factor | 1 / 0 | 4.1726 | 1 | 0.055296 | — | 0 | —–— (n=1) |
| normal_satellite_mobility | shortest_latency | 1 / 0 | 4.1726 | 1 | 0.055296 | — | 0 | —–— (n=1) |

Paired differences are multi-factor minus shortest-latency. The small-sample t intervals are exploratory and do not establish significance.

Failed runs remain in the per-run export and are counted above. Null metrics mean unavailable or undefined, never zero.

## Metric and model notes

mean delivered packet latency, milliseconds

Route-computation CPU time and time-integrated active-link availability are unavailable in current instrumentation. Satellite movement is the existing deterministic circular projection, not orbital mechanics.
