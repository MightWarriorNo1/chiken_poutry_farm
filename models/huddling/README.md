# huddling

Computes a clustering / huddling score over normalized bird centroids.

## Versions

| Version | Status | Notes |
|---|---|---|
| _none yet_ | _Sprint 5_ | DBSCAN over centroids in normalized [0,1] image coords. Zone-aware via bbox split. |

## Roadmap

1. **v1.0.0** — DBSCAN baseline. Tunable `eps`, `min_samples`. _Sprint 5_
2. **v2.0.0** — temporal smoothing (huddling persistence over N frames). _Production_
