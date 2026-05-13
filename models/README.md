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
# 1. Drop your labeled data under datasets/bird-detector/ in YOLO format:
#       datasets/bird-detector/images/{train,val,test}/*.jpg
#       datasets/bird-detector/labels/{train,val,test}/*.txt   (class 0 = chicken)
#    See datasets/bird-detector.yaml for the full layout spec.

# 2. Fine-tune from the current v1.0.0 checkpoint (YOLOv8n, chicken-tuned):
python scripts/train_bird_detector.py \
    --data datasets/bird-detector.yaml \
    --epochs 80 --imgsz 640 --version 1.1.0

# Or start from a larger COCO base (slower, needs more data, won't fit
# Jetson Nano realtime — only for off-device inference):
python scripts/train_bird_detector.py \
    --weights yolov8m.pt --data datasets/bird-detector.yaml \
    --epochs 100 --version 1.1.0

# 3. Promote and bump device config:
cd models/bird-detector && ln -snf 1.1.0 latest
```

The script writes `model.pt`, `model.onnx`, `metadata.json`, and an `eval.md`
stub into `models/bird-detector/<version>/`. Inspect the eval metrics and
spot-check predictions before promoting `latest`.

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
