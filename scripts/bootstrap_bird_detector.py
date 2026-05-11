"""Bootstrap a YOLOv8n bird-detector artifact into models/bird-detector/v1.0.0/.

Downloads the pretrained YOLOv8n checkpoint from Ultralytics, exports to ONNX, and
writes metadata.json. Safe to re-run; existing files are overwritten.

Usage:
    python scripts/bootstrap_bird_detector.py
    python scripts/bootstrap_bird_detector.py --imgsz 640 --version v1.0.0
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="v1.0.0", help="Output version directory name.")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--opset", type=int, default=17)
    parser.add_argument(
        "--checkpoint", default="yolov8n.pt",
        help="Ultralytics checkpoint name or path; downloaded on first run.",
    )
    args = parser.parse_args()

    try:
        from ultralytics import YOLO  # noqa: PLC0415
    except ImportError:
        print("Install with: pip install -e '.[ai]'")
        return 1

    out_dir = Path("models/bird-detector") / args.version
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading {args.checkpoint}...")
    yolo = YOLO(args.checkpoint)

    print(f"Exporting to ONNX (imgsz={args.imgsz}, opset={args.opset})...")
    exported = yolo.export(
        format="onnx",
        imgsz=args.imgsz,
        opset=args.opset,
        dynamic=False,
        simplify=True,
    )
    onnx_target = out_dir / "model.onnx"
    shutil.move(str(exported), onnx_target)
    print(f"  → {onnx_target}")

    metadata = {
        "name": "bird-detector",
        "version": args.version,
        "framework": "ultralytics-yolov8n",
        "format": "onnx",
        "input": {
            "shape": [1, 3, args.imgsz, args.imgsz],
            "dtype": "float32",
            "layout": "nchw",
        },
        "classes": ["bird"],
        "class_id_map": {"bird": 14},
        "thresholds": {"confidence": 0.25, "iou": 0.45},
        "trained_on": "MS COCO (pretrained)",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "notes": (
            "Pretrained YOLOv8n; uses COCO class 14 (bird) as a poultry proxy. "
            "Replace with a fine-tuned poultry model in Sprint 4."
        ),
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"  → {out_dir / 'metadata.json'}")
    print("\nDone. Point EdgeConfig.ai.models[bird-detector].version at", args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
