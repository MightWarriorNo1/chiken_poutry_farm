# bird-detector

Detects birds in poultry-shed camera frames and emits centroids + confidence.

## Versions

| Version | Status | Materialize with |
|---|---|---|
| **v1.0.0** | ✅ Available (Sprint 2) | `python scripts/bootstrap_bird_detector.py` |
| stub-0.0.1 | Always available | No download — `StubBirdDetector` emits synthetic events |

The model binary (`model.onnx`) is **not committed** — it's downloaded by the bootstrap
script (gitignored). The directory's `metadata.json` and `eval.md` are version-controlled.

## How to switch the running model

The active model is decided by `EdgeConfig.ai.models`:

```yaml
ai:
  models:
    - name: bird-detector
      version: v1.0.0    # or stub-0.0.1 for offline demos
```

For cloud-driven config this is pushed by the API. For offline development, edit
[`example.config.yaml`](../../example.config.yaml). The [InferenceSupervisor](../../src/edge/supervisors/inference_supervisor.py)
hot-swaps detectors on the next config poll — no edge restart needed.

If a version can't be loaded (file missing, ONNX corrupt) the supervisor falls
back to the stub and logs `inference.bird.load_failed`. The edge keeps running.

## Roadmap

1. **v1.0.0** — pretrained YOLOv8n, COCO `bird` class. Baseline. _Sprint 2 — current_
2. **v1.1.0** — fine-tuned on first 1k labeled poultry-shed frames. Better recall on dense layouts. _Sprint 4_
3. **v2.0.0** — ONNX → TensorRT FP16 on Jetson, ~3× throughput. _Production_
