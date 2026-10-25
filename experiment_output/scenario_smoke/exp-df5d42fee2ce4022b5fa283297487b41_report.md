# Experiment exp-df5d42fee2ce4022b5fa283297487b41

Scenario: `high_traffic_load` — Traffic rate is increased eightfold over configured intensity.
Status: **completed**; storage: `local_export_only`; elapsed: 0.149s

| Scenario | Algorithm | Successful / failed | Mean latency (ms) | PDR | Throughput (Mbps) | Recovery (ms) | Reroutes | Latency 95% CI |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| high_traffic_load | multi_factor | 1 / 0 | 4.2254 | 0.99438 | 0.3625 | — | 0 | —–— (n=1) |
| high_traffic_load | shortest_latency | 1 / 0 | 4.2254 | 0.99438 | 0.3625 | — | 0 | —–— (n=1) |

Paired differences are multi-factor minus shortest-latency. The small-sample t intervals are exploratory and do not establish significance.

Failed runs remain in the per-run export and are counted above. Null metrics mean unavailable or undefined, never zero.

## Metric and model notes

mean delivered packet latency, milliseconds

Route-computation CPU time and time-integrated active-link availability are unavailable in current instrumentation. Satellite movement is the existing deterministic circular projection, not orbital mechanics.
