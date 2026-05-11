"""Bootstrap models/bird-detector/v1.0.0/ with pretrained YOLOv8n.

Downloads the YOLOv8n COCO weights from Ultralytics (~6 MB), exports to ONNX,
and writes metadata.json + eval.md alongside.

Run once per dev machine:
    python scripts/download_yolov8n.py

The artifact (model.onnx) is gitignored — bootstrap on each machine, or pull
from a model registry / Git LFS in production.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET_DIR = Path("models/bird-detector/v1.0.0")


def main() -> int:
    try:
        from ultralytics import YOLO  # noqa: PLC0415
    except ImportError:
        print("Install with: pip install -e '.[ai]'  (needs ultralytics)", file=sys.stderr)
        return 1

    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    print("Downloading YOLOv8n COCO weights (~6 MB)...")
    model = YOLO("yolov8n.pt")

    print(f"Exporting to ONNX → {TARGET_DIR}/model.onnx")
    onnx_path = Path(model.export(format="onnx", imgsz=640, simplify=True))

    artifact_dst = TARGET_DIR / "model.onnx"
    if artifact_dst.exists():
        artifact_dst.unlink()
    shutil.move(str(onnx_path), str(artifact_dst))

    metadata = {
        "name": "bird-detector",
        "version": "1.0.0",
        "framework": "ultralytics-yolov8n",
        "format": "onnx",
        "artifact": "model.onnx",
        "input": {
            "shape": [1, 3, 640, 640],
            "dtype": "float32",
            "layout": "nchw",
            "color_space": "rgb",
            "normalize": "0-1",
        },
        "classes": [{"id": 14, "name": "bird"}],
        "thresholds": {"confidence": 0.25, "iou": 0.45},
        "trained_on": "coco-yolov8n-pretrained",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "notes": (
            "Bootstrap: pretrained YOLOv8n COCO. Filters to class 14 (bird). "
            "Replace with poultry-fine-tuned variant in v1.1.0+."
        ),
    }
    (TARGET_DIR / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )

    eval_md = """# bird-detector v1.0.0 — Evaluation

## Source
Pretrained YOLOv8n from Ultralytics on COCO. No fine-tuning yet.

## Acceptance for PoC
Used as a baseline to prove the inference pipeline. Expectations:
- Recall on actual chickens: low to moderate. COCO `bird` is dominated by wild
  birds; chickens overlap visually but not perfectly.
- False positives: occasional in cluttered scenes.

This is enough to demonstrate the end-to-end flow (frame → AI → outbox → cloud).
Real PoC accuracy lands in v1.1.0 after fine-tuning on labeled poultry data.

## Next steps
- Sprint 4: collect ~1k labeled poultry-shed frames (mix of breeds, lighting).
- Train fine-tuned YOLOv8n variant → v1.1.0.
- Re-export to ONNX, re-benchmark, update this file.
"""
    (TARGET_DIR / "eval.md").write_text(eval_md, encoding="utf-8")

    print(f"\n✓ Model artifact: {artifact_dst}")
    print(f"✓ Metadata:       {TARGET_DIR / 'metadata.json'}")
    print(f"✓ Eval notes:     {TARGET_DIR / 'eval.md'}")
    print("\nNext: python scripts/benchmark_inference.py --version 1.0.0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
