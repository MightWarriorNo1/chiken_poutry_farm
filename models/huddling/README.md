# huddling-detector

Computes a clustering / huddling score over normalized bird centroids.

## Versions

| Version | Status | Notes |
|---|---|---|
| `stub-0.0.1` | ✅ Always available | Emits constant 0.1 — for plumbing demos. |
| [`0.1.0`](v0.1.0/) | ✅ Sprint 5 | DBSCAN over centroids. Tunable `eps`, `min_samples`, per-zone overrides. No model artifact required (params live in metadata.json). |
| `1.0.0` | 🚧 Production | Temporal smoothing — rolling window over N frames to dedupe flapping alerts. |

## Selecting the version

```yaml
ai:
  models:
    - name: huddling-detector
      version: "0.1.0"
```

The `InferenceSupervisor` hot-swaps behind the `ProxiedHuddlingDetector` at the
next config poll — running camera pipelines keep going.

## Tuning per camera

If a camera has unusual framing, drop a `zone_overrides` block into
[v0.1.0/metadata.json](v0.1.0/metadata.json):

```json
"zone_overrides": {
  "zone-A": { "eps": 0.08, "min_samples": 6 }
}
```

The detector picks the override when `detection.zone_id` matches.
