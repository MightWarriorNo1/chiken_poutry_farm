# weight-estimator

Estimates average flock weight from a frame + breed + age inputs.

## Versions

| Version | Status | Notes |
|---|---|---|
| `stub-0.0.1` | ✅ Always available | `StubWeightEstimator` — fixed 1500g @ confidence 0.05 for plumbing demos. |
| [`0.1.0`](v0.1.0/) | ✅ Sprint 4 | Heuristic baseline — linear interpolation over breed growth curves. No model file required (curves live in metadata.json). |
| `1.0.0` | 🚧 Sprint 6+ | Regression model on detection features → weight. Trained on ~1000 manual samples. |
| `2.0.0` | 🔮 Production | Vision regression CNN on full frames + ground truth. |

## Selecting the version

Set in your `EdgeConfig.ai.models`:
```yaml
ai:
  models:
    - name: weight-estimator
      version: "0.1.0"        # or stub-0.0.1
```

The `InferenceSupervisor` swaps the active estimator behind the
`ProxiedWeightEstimator` at the next config poll — running camera pipelines
keep going.

## Cloud-side inputs

The heuristic needs `bird_age_days` and `breed`. These come from the camera
config (the cloud computes them from the flock's placement date / breed):

```yaml
cameras:
  - camera_id: cam-1
    source_uri: rtsp://...
    shed_id: shed-1
    flock_id: flock-A
    flock_age_days: 28
    breed: ross_308
```
