"""Export an Ultralytics YOLO checkpoint to ONNX for runtime use.

Usage:
    python scripts/export_to_onnx.py --weights runs/train/exp/weights/best.pt \
                                     --output models/bird-detector/v1.0.0/model.onnx
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--opset", type=int, default=17)
    args = parser.parse_args()

    try:
        from ultralytics import YOLO
    except ImportError:
        print("Install with: pip install -e '.[ai]'")
        return 1

    model = YOLO(str(args.weights))
    onnx_path = model.export(format="onnx", imgsz=args.imgsz, opset=args.opset, dynamic=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    Path(onnx_path).rename(args.output)
    print(f"Exported: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
