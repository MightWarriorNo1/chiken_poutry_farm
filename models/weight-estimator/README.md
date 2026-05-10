# weight-estimator

Estimates average flock weight from a frame + breed + age inputs.

## Versions

| Version | Status | Notes |
|---|---|---|
| _none yet_ | _Sprint 4_ | Heuristic v0.1: pixel area / bird × breed-age lookup. Calibrated per-camera. |

## Roadmap

1. **v0.1.0** — heuristic baseline. _Sprint 4_
2. **v1.0.0** — gradient-boosted regression on (image features, age, breed) → weight. _Sprint 6+_
3. **v2.0.0** — vision regression model (CNN) trained on weighed-sample ground truth. _Production_
