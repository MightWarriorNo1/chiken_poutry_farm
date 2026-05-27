"""Fine-tune YOLOv8-segmentation on labeled poultry data → deploys to TWO
model directories (huddling + mask-area weight estimator).

The same `.pt` artifact powers both:
  - `huddling-detector/<version>-seg/model.pt`  → SegHuddlingDetector
  - `weight-estimator/<version>-mask-area/model.pt` → MaskAreaWeightEstimator

So one training run unlocks two algorithm options in the dashboard dropdowns.

Usage
-----
    # 1. Stage a Roboflow seg export (if not already done):
    python scripts/prepare_yolo_seg_dataset.py \\
        --src "Chicken.v18i.yolov8" --name chicken-seg

    # 2. Train + auto-deploy:
    python scripts/train_seg.py \\
        --data datasets/chicken-seg/data.yaml \\
        --epochs 80 \\
        --version 1.0.0

    # 3. Restart prosper-edge, switch dropdowns in dashboard:
    #    Huddling method   → "YOLOv8-seg — mask-overlap clustering"
    #    Weight method     → "Mask-area — YOLOv8-seg + linear regression"
    # (Weight reports 0g until you also run scripts/fit_weight_regression.py)

Recovery
--------
After a crash mid-finalize, re-run without retraining:
    python scripts/train_seg.py --from-run runs/segment/chicken-seg-20260515-101200

Notes
-----
* Single-class fine-tune; dataset YAML must declare `names: {0: chicken}`.
  `prepare_yolo_seg_dataset.py` handles this automatically.
* Jetson Orin NX 16 GB defaults: batch=8, cache=ram, workers=4. Drop batch
  to 4 if OOM (rare). RTX 3060+ dev box can push batch=16.
* No ONNX export by default — seg ONNX is finicky and the Jetson uses .pt
  via ultralytics anyway. Pass --export-onnx to try it.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = REPO_ROOT / "datasets" / "chicken-seg" / "data.yaml"
DEFAULT_WEIGHTS = "yolov8n-seg.pt"  # downloaded by ultralytics on first use


def _normalize_data_yaml(yaml_path: Path) -> Path:
    """Rewrite the dataset YAML with an absolute `path:` and return its location.

    Same rationale as scripts/train_bird_detector.py — ultralytics resolves
    relative `path:` against its global datasets_dir, not the YAML's directory.
    """
    import yaml  # noqa: PLC0415

    cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    raw_path = cfg.get("path", ".")
    base = Path(str(raw_path)).expanduser()
    if not base.is_absolute():
        base = (yaml_path.parent / base).resolve()
    if not base.is_dir():
        raise FileNotFoundError(
            f"Dataset root resolved to {base} (from `path: {raw_path}` in "
            f"{yaml_path}), but that directory does not exist. Did you run "
            "scripts/prepare_yolo_seg_dataset.py?"
        )
    cfg["path"] = str(base)

    out_dir = REPO_ROOT / "runs"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"_normalized_{yaml_path.stem}_seg.yaml"
    out_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return out_path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--data", type=Path, default=DEFAULT_DATA)
    p.add_argument(
        "--weights",
        default=DEFAULT_WEIGHTS,
        help="Starting weights (default: yolov8n-seg.pt — downloaded on first run).",
    )
    p.add_argument(
        "--version",
        default="1.0.0",
        help=(
            "Base version string. Deployed dirs become "
            "models/huddling-detector/<version>-seg/ and "
            "models/weight-estimator/<version>-mask-area/."
        ),
    )
    p.add_argument("--epochs", type=int, default=80)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument(
        "--batch",
        type=int,
        default=8,
        help="Jetson-safe default. RTX 3060+ can use 16. -1 = ultralytics auto.",
    )
    p.add_argument("--patience", type=int, default=20)
    p.add_argument("--device", default="", help='Device, e.g. "0", "cpu", or empty=auto.')
    p.add_argument("--workers", type=int, default=4)
    p.add_argument(
        "--cache",
        default="ram",
        choices=("ram", "disk", "false"),
        help="Cache images for faster epochs (default ram).",
    )
    p.add_argument("--name", default="", help="Run name; auto-timestamped if empty.")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument(
        "--export-onnx",
        action="store_true",
        help="Try to export ONNX too. Often fails for seg; .pt always works.",
    )
    p.add_argument(
        "--no-promote",
        action="store_true",
        help="Skip copying best.pt into the model directories.",
    )
    p.add_argument(
        "--skip-huddling",
        action="store_true",
        help="Promote only to weight-estimator/, not huddling-detector/.",
    )
    p.add_argument(
        "--skip-weight",
        action="store_true",
        help="Promote only to huddling-detector/, not weight-estimator/.",
    )
    p.add_argument(
        "--from-run",
        type=Path,
        default=None,
        help=(
            "Skip training; finalize from an existing run dir "
            "(e.g. runs/segment/chicken-seg-20260515-101200). "
            "Useful for recovering from a post-training failure."
        ),
    )
    return p.parse_args()


def _promote_to_huddling(
    best_pt: Path,
    version: str,
    metrics: dict,
    source_data: str,
    base_weights: str,
    imgsz: int,
    run_dir_rel: str,
) -> Path:
    """Deploy .pt + metadata.json + eval.md into huddling-detector/<version>-seg/."""
    target_dir = REPO_ROOT / "models" / "huddling-detector" / f"{version}-seg"
    target_dir.mkdir(parents=True, exist_ok=True)

    pt_dst = target_dir / "model.pt"
    if pt_dst.exists():
        pt_dst.unlink()
    shutil.copy(best_pt, pt_dst)

    metadata = {
        "name": "huddling-detector",
        "version": f"{version}-seg",
        "framework": "ultralytics-yolov8-seg",
        "format": "pytorch",
        "algorithm": "yolo-seg",
        "artifact": "model.pt",
        "input": {"shape": [1, 3, imgsz, imgsz]},
        "dilate_px": 30,
        "thresholds": {"confidence": 0.25, "iou": 0.45},
        "trained_on": source_data,
        "base_weights": base_weights,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "training": {"run_dir": run_dir_rel, "imgsz": imgsz},
        "metrics": metrics,
        "notes": (
            "YOLOv8-seg checkpoint shared with weight-estimator's mask-area "
            "version. Mask-overlap clustering for huddle detection."
        ),
    }
    (target_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return target_dir


def _promote_to_weight(
    best_pt: Path,
    version: str,
    metrics: dict,
    source_data: str,
    base_weights: str,
    imgsz: int,
    run_dir_rel: str,
) -> Path:
    """Deploy .pt + metadata.json into weight-estimator/<version>-mask-area/.

    Regression coefficients are zeroed — run scripts/fit_weight_regression.py
    after receiving the client's calibration CSV to populate them.
    """
    target_dir = REPO_ROOT / "models" / "weight-estimator" / f"{version}-mask-area"
    target_dir.mkdir(parents=True, exist_ok=True)

    pt_dst = target_dir / "model.pt"
    if pt_dst.exists():
        pt_dst.unlink()
    shutil.copy(best_pt, pt_dst)

    metadata = {
        "name": "weight-estimator",
        "version": f"{version}-mask-area",
        "framework": "ultralytics-yolov8-seg",
        "format": "pytorch",
        "algorithm": "mask-area",
        "artifact": "model.pt",
        "input": {"shape": [1, 3, imgsz, imgsz]},
        # Regression coefficients are placeholders until the client's
        # calibration CSV is fitted via scripts/fit_weight_regression.py.
        "regression": {"slope": 0.0, "intercept": 0.0},
        "camera_calibration": {},
        "fallback_ref_area_px": 10000.0,
        "thresholds": {"confidence": 0.25, "iou": 0.45},
        "baseline_confidence": 0.65,
        "trained_on": source_data,
        "base_weights": base_weights,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "training": {"run_dir": run_dir_rel, "imgsz": imgsz},
        "seg_metrics": metrics,
        "notes": (
            "Mask-area weight regression. Same YOLOv8-seg checkpoint as "
            "huddling-detector/<version>-seg. The regression slope/intercept "
            "above are PLACEHOLDERS — run scripts/fit_weight_regression.py "
            "on the client's calibration CSV to populate them."
        ),
    }
    (target_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return target_dir


def main() -> int:
    args = parse_args()

    try:
        from ultralytics import YOLO  # noqa: PLC0415
    except ImportError:
        print("Install training deps with: pip install ultralytics", file=sys.stderr)
        return 1

    source_data_path = args.data.resolve()
    if not source_data_path.is_file():
        print(f"Dataset YAML not found: {source_data_path}", file=sys.stderr)
        print(
            "Run scripts/prepare_yolo_seg_dataset.py first to stage the dataset.",
            file=sys.stderr,
        )
        return 1

    try:
        data_path = _normalize_data_yaml(source_data_path)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"▶ Normalized data YAML: {data_path}")

    cache_value: bool | str = True if args.cache == "ram" else (
        "disk" if args.cache == "disk" else False
    )

    if args.from_run is not None:
        run_dir = args.from_run.resolve()
        best_pt = run_dir / "weights" / "best.pt"
        if not best_pt.is_file():
            print(f"--from-run: best.pt missing at {best_pt}", file=sys.stderr)
            return 1
        print(f"▶ Skipping training, finalizing from: {run_dir}")
    else:
        run_name = args.name or f"chicken-seg-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        print(f"▶ Loading weights: {args.weights}")
        model = YOLO(args.weights)

        print(f"▶ Training on {data_path} → runs/segment/{run_name}/")
        train_results = model.train(
            task="segment",
            data=str(data_path),
            epochs=args.epochs,
            imgsz=args.imgsz,
            batch=args.batch,
            patience=args.patience,
            device=args.device or None,
            workers=args.workers,
            cache=cache_value,
            project="runs/segment",
            name=run_name,
            seed=args.seed,
            cos_lr=True,
            amp=True,
            mosaic=0.5,
            close_mosaic=10,
            exist_ok=False,
        )
        run_dir = Path(
            getattr(train_results, "save_dir", REPO_ROOT / "runs" / "segment" / run_name)
        )
        best_pt = run_dir / "weights" / "best.pt"
        if not best_pt.is_file():
            print(f"Training finished but best.pt missing at {best_pt}", file=sys.stderr)
            return 2

    print("▶ Validating best.pt")
    val_model = YOLO(str(best_pt))
    val_results = val_model.val(
        task="segment",
        data=str(data_path),
        imgsz=args.imgsz,
        device=args.device or None,
    )

    # Both `box` and `seg` namespaces exist on segmentation results.
    box = getattr(val_results, "box", None)
    seg = getattr(val_results, "seg", None)
    metrics = {
        "box_mAP50": float(getattr(box, "map50", 0.0)) if box else 0.0,
        "box_mAP50_95": float(getattr(box, "map", 0.0)) if box else 0.0,
        "mask_mAP50": float(getattr(seg, "map50", 0.0)) if seg else 0.0,
        "mask_mAP50_95": float(getattr(seg, "map", 0.0)) if seg else 0.0,
    }

    if args.no_promote:
        print(f"✓ Done. Best weights: {best_pt}  (skipping promote)")
        print(f"  metrics: {metrics}")
        return 0

    source_data_rel = (
        str(source_data_path.relative_to(REPO_ROOT))
        if source_data_path.is_relative_to(REPO_ROOT)
        else str(source_data_path)
    )
    run_dir_rel = (
        str(run_dir.relative_to(REPO_ROOT))
        if run_dir.is_relative_to(REPO_ROOT)
        else str(run_dir)
    )

    if not args.skip_huddling:
        target = _promote_to_huddling(
            best_pt, args.version, metrics, source_data_rel,
            args.weights, args.imgsz, run_dir_rel,
        )
        print(f"✓ Deployed to:   {target / 'model.pt'}")
        print(f"                 {target / 'metadata.json'}")

    if not args.skip_weight:
        target = _promote_to_weight(
            best_pt, args.version, metrics, source_data_rel,
            args.weights, args.imgsz, run_dir_rel,
        )
        print(f"✓ Deployed to:   {target / 'model.pt'}")
        print(f"                 {target / 'metadata.json'}  (regression: 0,0 — fit later)")

    if args.export_onnx:
        try:
            print("▶ Exporting ONNX (best-effort; segmentation often fails)")
            onnx_path = Path(
                val_model.export(format="onnx", imgsz=args.imgsz, opset=17, simplify=True)
            )
            # Drop alongside the .pt in both target dirs
            for sub in ("huddling-detector", "weight-estimator"):
                suffix = "-seg" if sub == "huddling-detector" else "-mask-area"
                td = REPO_ROOT / "models" / sub / f"{args.version}{suffix}"
                if td.exists() and (td / "model.pt").is_file():
                    shutil.copy(onnx_path, td / "model.onnx")
                    print(f"✓ ONNX:          {td / 'model.onnx'}")
        except Exception as exc:  # noqa: BLE001
            print(
                f"⚠ ONNX export failed ({type(exc).__name__}: {exc}). "
                "Continuing with model.pt only — Jetson uses .pt at runtime.",
                file=sys.stderr,
            )

    print()
    print(f"  metrics: {metrics}")
    print()
    print("Next steps:")
    print("  1. Restart prosper-edge")
    print("  2. Overview tab → Huddling method dropdown → select 'YOLOv8-seg'")
    print(f"  3. (Once client's calibration CSV is in) python scripts/fit_weight_regression.py \\")
    print(f"        --model models/huddling-detector/{args.version}-seg/model.pt \\")
    print(f"        --weights-csv path/to/weights.csv \\")
    print(f"        --images-dir path/to/photos/")
    print(f"     Then paste slope/intercept into the weight-estimator metadata.json")
    print("     and select 'Mask-area' in the Weight method dropdown.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
