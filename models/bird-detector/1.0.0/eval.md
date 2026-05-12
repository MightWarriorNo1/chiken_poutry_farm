# bird-detector v1.0.0 — Evaluation

## Source
Pretrained **YOLOv8n** (Ultralytics) trained on COCO. No fine-tuning yet.
Bootstrap with `python scripts/download_yolov8n.py`.

## Acceptance for PoC
Baseline to prove the inference pipeline end-to-end. Expectations:
- Recall on actual chickens: low to moderate. COCO `bird` (class id 14) is
  dominated by wild birds; chickens overlap visually but not perfectly.
- False positives: occasional in cluttered shed scenes.

That's enough to demonstrate **frame → AI → outbox → cloud**, which is the
Sprint 2 goal. Real PoC accuracy lands in v1.1.0 after fine-tuning on labeled
poultry data.

## Reproducing
```bash
python scripts/download_yolov8n.py
python scripts/benchmark_inference.py --version 1.0.0
```

## Next steps
- Sprint 4: collect ~1k labeled poultry-shed frames (mix of breeds, lighting).
- Train fine-tuned YOLOv8n → v1.1.0; re-export to ONNX; re-benchmark; update this file.
