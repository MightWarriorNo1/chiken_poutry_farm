# huddling-detector v0.1.0 — Evaluation

## Source
DBSCAN clustering over normalized bird centroids (the [0, 1] image-coordinate
points the `bird-detector` already produces). Parameters live in
[metadata.json](metadata.json).

## How it scores

For a frame with N detected birds:
1. Cluster the centroids with DBSCAN (`eps`, `min_samples`).
2. `cluster_count` = number of clusters found (label != -1).
3. `largest_cluster_pct` = fraction of birds in the biggest cluster.
4. `huddling_score` = `largest_cluster_pct`.

This means:
| Pattern | Result |
|---|---|
| All birds in one tight blob (panic / cold huddle) | `huddling_score` near 1.0 |
| Even spread across the shed | `huddling_score` near 0.0 |
| Half clustered, half wandering | `huddling_score` around 0.4–0.5 |
| Three small distinct groups | Low `huddling_score`, `cluster_count` = 3 |

The cloud is free to combine `huddling_score` and `cluster_count` for richer
alerting (e.g. "many small clusters" is different from "one big blob").

## Tuning

`eps = 0.05` works as a starting point for a wide-angle shed camera (5% of frame
width). For closer / narrower cameras, increase to 0.08–0.10. Use
`zone_overrides` for cameras whose zones have different bird densities.

## Acceptance for PoC
- Correctly distinguishes "tight cluster" from "spread" in synthetic tests.
- Stable on real footage (no per-frame thrashing — DBSCAN is deterministic).

## Next steps
- Sprint 6+: real-footage tuning + per-zone params from a week of recorded
  shed video.
- v1.0.0: add temporal smoothing (rolling-window mean to deduplicate flapping
  alerts).
