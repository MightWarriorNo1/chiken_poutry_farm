"""Fine-tune YOLOv8 on labeled poultry data → models/bird-detector/<version>/.

Defaults continue training from the current production checkpoint
(`models/bird-detector/1.0.0/model.pt`, YOLOv8n, single class `chicken`).
Override `--weights` to start from stock COCO weights or a different
architecture (e.g. `yolov8m.pt`).

Usage
-----
    # 1. Prepare a YOLO-format dataset; see datasets/bird-detector.yaml.
    # 2. Run:
    python scripts/train_bird_detector.py \\
        --data datasets/bird-detector.yaml \\
        --epochs 80 \\
        --imgsz 640 \\
        --version 1.1.0

    # 3. After training:
    #    - best weights → models/bird-detector/<version>/model.pt
    #    - ONNX export  → models/bird-detector/<version>/model.onnx
    #    - metadata.json + eval.md stubs written alongside.
    # 4. Promote: cd models/bird-detector && ln -snf <version> latest
    # 5. Bump EdgeConfig.ai.models[*].version on the device.

Notes
-----
* Single-class fine-tune. The dataset YAML must declare `names: {0: chicken}`
  to stay schema-compatible with v1.0.0 metadata and the inference factory.
* Mixed-arch resume: you cannot resume a yolov8m run from a yolov8n .pt
  checkpoint (the layer shapes differ). To go bigger, pass
  `--weights yolov8m.pt` and Ultralytics will start from COCO weights at
  that size — slower convergence but a clean run.
* Jetson Nano budget: yolov8n at 640² fits the realtime AI-frame interval.
  yolov8m is ~5–8× slower on Nano — only pick it if you're retargeting
  hardware (Xavier, Orin, x86 GPU) or running off-device inference.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WEIGHTS = REPO_ROOT / "models" / "bird-detector" / "1.0.0" / "model.pt"
DEFAULT_DATA = REPO_ROOT / "datasets" / "bird-detector.yaml"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA,
        help="Path to the YOLO-format dataset YAML (default: datasets/bird-detector.yaml).",
    )
    p.add_argument(
        "--weights",
        type=str,
        default=str(DEFAULT_WEIGHTS),
        help=(
            "Starting weights. Defaults to the v1.0.0 checkpoint (YOLOv8n, chicken-tuned). "
            "Pass `yolov8m.pt` (or any Ultralytics tag) to start from a larger COCO base."
        ),
    )
    p.add_argument("--version", default="1.1.0", help="Target model version (lands in models/bird-detector/<version>/).")
    p.add_argument("--epochs", type=int, default=80)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument(
        "--batch",
        type=int,
        default=-1,
        help="Batch size. -1 = Ultralytics auto-batch based on VRAM (recommended).",
    )
    p.add_argument("--patience", type=int, default=20, help="Early-stopping patience (epochs without val improvement).")
    p.add_argument("--device", default="", help='Device, e.g. "0", "0,1", or "cpu". Empty = auto.')
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--name", default="", help="Run name under runs/train/. Auto-timestamped if empty.")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--no-export", action="store_true", help="Skip ONNX export step.")
    p.add_argument(
        "--no-promote",
        action="store_true",
        help="Skip copying best.pt + metadata into models/bird-detector/<version>/.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    try:
        from ultralytics import YOLO  # noqa: PLC0415
    except ImportError:
        print("Install training deps with: pip install -e '.[ai]'", file=sys.stderr)
        return 1

    data_path = args.data.resolve()
    if not data_path.is_file():
        print(f"Dataset YAML not found: {data_path}", file=sys.stderr)
        print("See datasets/bird-detector.yaml for the expected layout.", file=sys.stderr)
        return 1

    run_name = args.name or f"bird-detector-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    print(f"▶ Loading weights: {args.weights}")
    model = YOLO(args.weights)

    print(f"▶ Training on {data_path} → runs/train/{run_name}/")
    train_results = model.train(
        data=str(data_path),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        patience=args.patience,
        device=args.device or None,
        workers=args.workers,
        project="runs/train",
        name=run_name,
        seed=args.seed,
        # Fine-tune-friendly defaults. Light augmentation; chickens don't
        # benefit from aggressive mosaics in confined shed scenes.
        cos_lr=True,
        amp=True,
        mosaic=0.5,
        close_mosaic=10,
        exist_ok=False,
    )

    # `train_results.save_dir` points to runs/train/<name>/.
    run_dir = Path(getattr(train_results, "save_dir", REPO_ROOT / "runs" / "train" / run_name))
    best_pt = run_dir / "weights" / "best.pt"
    if not best_pt.is_file():
        print(f"Training finished but best.pt missing at {best_pt}", file=sys.stderr)
        return 2

    # Validation pass on best.pt for honest metrics (Ultralytics already does
    # one at the end of training, but re-running gives us a stable handle to
    # the metrics dict for the eval.md stub).
    print("▶ Validating best.pt")
    val_model = YOLO(str(best_pt))
    val_results = val_model.val(data=str(data_path), imgsz=args.imgsz, device=args.device or None)

    if args.no_promote:
        print(f"✓ Done. Best weights: {best_pt}  (skipping promote/export)")
        return 0

    # Promote into models/bird-detector/<version>/
    target_dir = REPO_ROOT / "models" / "bird-detector" / args.version
    target_dir.mkdir(parents=True, exist_ok=True)
    pt_dst = target_dir / "model.pt"
    if pt_dst.exists():
        pt_dst.unlink()
    shutil.copy(best_pt, pt_dst)
    print(f"✓ Checkpoint:    {pt_dst}")

    onnx_dst: Path | None = None
    if not args.no_export:
        print("▶ Exporting ONNX (simplified, opset 17)")
        onnx_path = Path(val_model.export(format="onnx", imgsz=args.imgsz, opset=17, simplify=True))
        onnx_dst = target_dir / "model.onnx"
        if onnx_dst.exists():
            onnx_dst.unlink()
        shutil.move(str(onnx_path), str(onnx_dst))
        print(f"✓ ONNX:          {onnx_dst}")

    # Metrics — Ultralytics exposes them on the results.box namespace.
    box = getattr(val_results, "box", None)
    metrics = {
        "mAP50": float(getattr(box, "map50", 0.0)) if box else 0.0,
        "mAP50_95": float(getattr(box, "map", 0.0)) if box else 0.0,
        "precision": float(getattr(box, "mp", 0.0)) if box else 0.0,
        "recall": float(getattr(box, "mr", 0.0)) if box else 0.0,
    }

    metadata = {
        "name": "bird-detector",
        "version": args.version,
        "framework": "ultralytics-yolov8",
        "format": "pytorch",
        "artifact": "model.pt",
        "input": {
            "shape": [1, 3, args.imgsz, args.imgsz],
            "dtype": "float32",
            "layout": "nchw",
            "color_space": "rgb",
            "normalize": "0-1",
        },
        "classes": [{"id": 0, "name": "chicken"}],
        "thresholds": {"confidence": 0.25, "iou": 0.45},
        "trained_on": str(data_path.relative_to(REPO_ROOT)) if data_path.is_relative_to(REPO_ROOT) else str(data_path),
        "base_weights": args.weights,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "training": {
            "epochs": args.epochs,
            "imgsz": args.imgsz,
            "batch": args.batch,
            "seed": args.seed,
            "run_dir": str(run_dir.relative_to(REPO_ROOT)) if run_dir.is_relative_to(REPO_ROOT) else str(run_dir),
        },
        "metrics": metrics,
        "notes": (
            f"Fine-tuned from {args.weights}. Single-class chicken detector "
            "(class 0). Both model.pt and model.onnx ship in this folder; the "
            "inference factory picks the .pt path on Jetson (torch.cuda) and "
            "falls back to .onnx elsewhere."
        ),
    }
    (target_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"✓ Metadata:      {target_dir / 'metadata.json'}")

    eval_md = f"""# bird-detector v{args.version} — Evaluation

## Source
Fine-tuned from `{args.weights}` on `{metadata["trained_on"]}`.

## Run
- Run dir: `{metadata["training"]["run_dir"]}`
- Epochs: {args.epochs} (early-stop patience {args.patience})
- imgsz: {args.imgsz}, batch: {args.batch}, seed: {args.seed}

## Validation metrics (best.pt)
| Metric    | Value |
|-----------|-------|
| mAP@50    | {metrics["mAP50"]:.4f} |
| mAP@50:95 | {metrics["mAP50_95"]:.4f} |
| Precision | {metrics["precision"]:.4f} |
| Recall    | {metrics["recall"]:.4f} |

## Reproducing
```bash
python scripts/train_bird_detector.py \\
    --data {metadata["trained_on"]} \\
    --weights {args.weights} \\
    --epochs {args.epochs} --imgsz {args.imgsz} \\
    --version {args.version}
```

## Next steps
- Spot-check predictions on held-out shed footage.
- If recall on dark / heavily-occluded frames is weak, augment dataset
  and re-train into v{args.version}+1.
- After acceptance: `cd models/bird-detector && ln -snf {args.version} latest`,
  then bump `EdgeConfig.ai.models[*].version` on the device.
"""
    (target_dir / "eval.md").write_text(eval_md, encoding="utf-8")
    print(f"✓ Eval notes:    {target_dir / 'eval.md'}")

    print(
        f"\nNext: python scripts/benchmark_inference.py --version {args.version}"
        f"\n      cd models/bird-detector && ln -snf {args.version} latest"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
