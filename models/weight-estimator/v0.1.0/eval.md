# weight-estimator v0.1.0 — Evaluation

## Source
Lookup-table baseline. Standard broiler growth curves (Ross 308, Cobb 500,
Hubbard Classic) loaded from [metadata.json](metadata.json). Linear
interpolation between sample points; clamps below day 1 and above day 42.

## Acceptance for PoC
This is a **calibration baseline**, not a real CV model. It exists so the cloud
has a `WeightEstimate` event flowing end-to-end while we collect labeled samples
for v1.0.0. Confidence is intentionally capped at `baseline_confidence ×
detection.confidence` (default 0.4 × ~0.85 ≈ 0.34) so the dashboard can
deprioritize these readings versus a real model's outputs.

## Required inputs
| Field | Source |
|---|---|
| `bird_age_days` | Camera config (set on the cloud per flock) |
| `breed` | Camera config — falls back to `default_breed` if missing or unknown |

If either is missing, the heuristic emits `estimated_avg_weight_g=0` with
`confidence=0` so downstream can filter it out.

## How accurate?
For a healthy flock at the projected breed/age curve, the heuristic is
*tautologically* close to expectation — by design. It cannot detect that the
flock is below or above target. That's exactly what v1.0.0 will do.

## Next steps
- Sprint 6+: collect ~1000 manual-weight samples timestamp-paired with frames.
- Train regression model (xgboost on detection features → weight) → v1.0.0.
- Re-export, re-benchmark, update this file.
