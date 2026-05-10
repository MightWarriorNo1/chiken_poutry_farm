# AI Model Registry

Each model lives at `models/<name>/<version>/` with at minimum a `metadata.json` and
a `model.onnx` (or `model.pt` for training-only artifacts). A `latest` symlink
points to the active version.

```
models/
├── bird-detector/
│   ├── v1.0.0/
│   │   ├── model.onnx        # inference artifact (gitignored or LFS)
│   │   ├── metadata.json     # input shape, classes, thresholds
│   │   └── eval.md           # mAP, recall, dataset notes
│   └── latest -> v1.0.0
├── weight-estimator/
└── huddling/
```

## Adding a new model version

1. Train: `python scripts/train_<name>.py …` (lands in Sprint 2+).
2. Export: `python scripts/export_to_onnx.py --weights ... --output models/<name>/v<X>/model.onnx`
3. Write `metadata.json` (see template below).
4. Write `eval.md` with metrics + dataset reference.
5. Open PR. CI verifies `metadata.json` schema (TODO).
6. After merge, retarget `latest`: `cd models/<name> && ln -snf v<X> latest`.
7. Bump `EdgeConfig.ai.models[*].version` for the device(s).

## metadata.json template

```json
{
  "name": "bird-detector",
  "version": "1.0.0",
  "framework": "ultralytics-yolov8n",
  "format": "onnx",
  "input": {"shape": [1, 3, 640, 640], "dtype": "float32", "layout": "nchw"},
  "classes": ["bird"],
  "thresholds": {"confidence": 0.25, "iou": 0.45},
  "trained_on": "coco-bird + poultry-internal-v0",
  "trained_at": "2026-01-15T00:00:00Z"
}
```
