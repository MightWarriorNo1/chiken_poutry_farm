# bird-detector v1.0.0 — Evaluation

## Provenance
- **Source:** Ultralytics YOLOv8n, pretrained on MS COCO.
- **Export:** ONNX opset 17, fixed input 1×3×640×640.
- **Bird class:** COCO class id `14` (`bird`).
- **Bootstrap command:** `python scripts/bootstrap_bird_detector.py`

## Why pretrained for v1.0.0?
- **Zero data cost.** PoC demos can run before any poultry data exists.
- **Conservative baseline.** Public COCO numbers (mAP@0.5 = 0.527 for the bird
  class) are a known reference point.
- **Forward-compatible.** v1.x can fine-tune on collected farm footage; the
  inference adapter and contract don't change.

## Known limitations
- COCO `bird` is dominated by passerines, not poultry. Expect lower recall on
  densely-packed white chicks and adult layers in commercial sheds.
- 640×640 input downsamples 1080p shed cameras significantly — small birds in
  the back of the frame may be missed.
- No temporal smoothing — a bird that walks behind another for one frame can
  oscillate in count.

## Roadmap
- **v1.1.0** — fine-tune on the first 1k labeled poultry-shed frames once they
  exist. Target: +30% recall on dense layouts.
- **v2.0.0** — ONNX → TensorRT FP16 for Jetson, ≥3× throughput target.

## Benchmark (host-dependent)
Run on each host to record:
```
python scripts/benchmark_inference.py --version v1.0.0
```
Results table to be filled in as runs land. Reference targets:
- Dev laptop (CPU): ≥ 5 FPS at 1280×720
- Jetson Orin Nano (CUDA, fp32): ≥ 20 FPS
- Jetson Orin Nano (TensorRT, fp16): ≥ 40 FPS
