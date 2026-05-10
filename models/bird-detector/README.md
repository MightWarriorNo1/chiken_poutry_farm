# bird-detector

Detects birds in poultry-shed camera frames and emits centroids + confidence.

## Versions

| Version | Status | Notes |
|---|---|---|
| _none yet_ | _Sprint 2_ | Bootstraps from YOLOv8n COCO `bird` class; fine-tune on poultry data after first labeled batch. |

## Roadmap

1. **v1.0.0** — pretrained YOLOv8n, COCO bird class only. Baseline mAP. _Sprint 2_
2. **v1.1.0** — fine-tuned on first 1k labeled poultry-shed frames. Improved recall in low light. _Sprint 4_
3. **v2.0.0** — ONNX → TensorRT FP16 on Jetson. ~3× throughput. _Production_
