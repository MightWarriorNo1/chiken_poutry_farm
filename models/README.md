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

1. Train: `python scripts/train_<name>.py …`
   For `bird-detector`, see [training the bird-detector](#training-the-bird-detector) below.
2. Export: handled by the train script, or manually:
   `python scripts/export_to_onnx.py --weights ... --output models/<name>/<X>/model.onnx`
3. Write `metadata.json` (see template below) — train script does this automatically.
4. Write `eval.md` with metrics + dataset reference — train script writes a stub.
5. Open PR. CI verifies `metadata.json` schema (TODO).
6. After merge, retarget `latest`: `cd models/<name> && ln -snf <X> latest`.
7. Bump `EdgeConfig.ai.models[*].version` for the device(s).

## Training the bird-detector

```bash
# 1. Get the dataset onto the training machine. Pick one:
#
#    (a) Pull directly from Roboflow on-device (preferred — no manual copy):
pip install --user roboflow
export ROBOFLOW_API_KEY=xxx     # from https://app.roboflow.com/settings/api
python scripts/download_roboflow_dataset.py \
    --url https://universe.roboflow.com/thesis-3c51t/chicken-counting/dataset/18 \
    --name chicken-counting
#    (auto-stages into datasets/chicken-counting/)

#    (b) Or, if the raw Roboflow folder is already on disk:
python scripts/prepare_yolo_dataset.py \
    --src "Chicken Counting.v18-chicken.yolov8" --name chicken-counting

# 2. Fine-tune. Default --data is datasets/bird-detector.yaml, which points
#    at the active staged dataset. Start from v1.0.0 (the chicken-aware
#    baseline) — earlier fine-tunes can be regenerated from this baseline.
python scripts/train_bird_detector.py \
    --weights models/bird-detector/1.0.0/model.pt \
    --epochs 80 --version 1.2.0

# Recover from a post-training failure (e.g. ONNX export crash) without
# retraining — finalize from an existing run dir:
python scripts/train_bird_detector.py \
    --from-run runs/detect/runs/train/bird-detector-<timestamp> \
    --version 1.2.0

# 3. Promote and bump device config:
cd models/bird-detector && ln -snf 1.2.0 latest
# Then edit your /etc/prosper-edge/config.yaml or ./config.yaml so the
# bird-detector entry uses version: "1.2.0".
```

The train script writes `model.pt`, `model.onnx` (best-effort), `metadata.json`,
and an `eval.md` stub into `models/bird-detector/<version>/`. Inspect the eval
metrics and spot-check on real shed footage before promoting `latest`.

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
