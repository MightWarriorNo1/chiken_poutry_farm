# bird-detector

Detects birds in poultry-shed camera frames and emits centroids + confidence.

## Versions

| Version | Status | Notes |
|---|---|---|
| `stub-0.0.1` | ✅ Always available | Synthetic detections. Used by `StubBirdDetector` for offline demos and contract validation. |
| [`1.0.0`](v1.0.0/) | ✅ Sprint 2 | Pretrained YOLOv8n COCO, filtered to `bird` class. Bootstrap with `scripts/download_yolov8n.py`. |
| `1.1.0` | 🚧 Sprint 4 | Fine-tuned on first ~1k labeled poultry-shed frames. |
| `2.0.0` | 🔮 Production | ONNX → TensorRT FP16 on Jetson. Same pipeline, ~3× throughput. |

## Bootstrap

```powershell
python scripts/download_yolov8n.py            # ~6 MB download → models/bird-detector/v1.0.0/model.onnx
python scripts/benchmark_inference.py --version 1.0.0
```

## Cloud-driven model selection

Set the active version in your `EdgeConfig.ai.models`:
```yaml
ai:
  models:
    - name: bird-detector
      version: "1.0.0"          # or stub-0.0.1 to fall back to the stub
```
The `InferenceSupervisor` picks up the change at the next config poll, hot-swaps
the detector behind the `ProxiedBirdDetector`, and running camera pipelines
continue without restart.
