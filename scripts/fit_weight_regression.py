"""Fit the mask-area → weight linear regression after the YOLOv8-seg is trained.

Workflow:
  1. Client provides: trained YOLOv8-seg model.pt + a CSV mapping image
     filenames to weights + a folder of those images.
  2. This script: runs the seg model on each image, extracts the mask
     of the chicken that's closest to the bbox the client annotated,
     pairs (mask_area_px, weight_g), and fits sklearn LinearRegression.
  3. Outputs the slope + intercept ready to paste into
     `models/weight-estimator/0.4.0-mask-area/metadata.json`.

Usage:
    python scripts/fit_weight_regression.py \
        --model runs/segment/train/weights/best.pt \
        --weights-csv calibration/weights.csv \
        --images-dir calibration/photos \
        --output regression.json

The CSV must have columns: `image_filename`, `weight_g`. Optionally
`bbox_x, bbox_y, bbox_w, bbox_h` (in pixels) to identify which chicken
in a multi-chicken photo is the weighed one. Without bbox, we assume
the largest detection is the weighed chicken.

Output `regression.json`:
    {"slope": ..., "intercept": ..., "ref_area_px": ...,
     "n_samples": ..., "r2": ..., "mae_g": ...}

Paste `slope`, `intercept`, and `ref_area_px` (under your camera_id in
`camera_calibration`) into the metadata.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class _Sample:
    image: Path
    weight_g: float
    bbox: tuple[float, float, float, float] | None  # (x, y, w, h) in pixels


def _load_csv(csv_path: Path, images_dir: Path) -> list[_Sample]:
    samples: list[_Sample] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "image_filename" not in reader.fieldnames:
            raise ValueError(
                "CSV must have columns: image_filename, weight_g "
                "(and optionally bbox_x, bbox_y, bbox_w, bbox_h)"
            )
        for row in reader:
            img = images_dir / row["image_filename"]
            if not img.is_file():
                print(f"WARN: image not found, skipping: {img}", file=sys.stderr)
                continue
            try:
                weight = float(row["weight_g"])
            except (KeyError, ValueError):
                print(f"WARN: bad weight on row {row}, skipping", file=sys.stderr)
                continue
            bbox = None
            if all(k in row and row[k] for k in ("bbox_x", "bbox_y", "bbox_w", "bbox_h")):
                bbox = (
                    float(row["bbox_x"]),
                    float(row["bbox_y"]),
                    float(row["bbox_w"]),
                    float(row["bbox_h"]),
                )
            samples.append(_Sample(image=img, weight_g=weight, bbox=bbox))
    return samples


def _mask_area_for_sample(model, sample: _Sample) -> float | None:
    """Return the mask area (px²) of the chicken matching the labeled bbox,
    or the largest mask if no bbox provided. None if nothing detected."""
    import cv2
    import numpy as np

    img = cv2.imread(str(sample.image))
    if img is None:
        return None
    results = model.predict(img, verbose=False)
    if not results:
        return None
    r = results[0]
    if r.masks is None or r.masks.data is None or len(r.masks.data) == 0:
        return None

    try:
        masks = r.masks.data.cpu().numpy()
    except AttributeError:
        masks = np.asarray(r.masks.data, dtype=np.float32)
    bin_masks = (masks > 0.5).astype(np.uint8)

    if sample.bbox is None:
        # No bbox label — assume the largest mask is the weighed chicken.
        areas = [int(m.sum()) for m in bin_masks]
        idx = int(np.argmax(areas))
        return float(areas[idx])

    # Pick the mask whose centroid is closest to the bbox center.
    bx, by, bw, bh = sample.bbox
    target_cx = bx + bw / 2
    target_cy = by + bh / 2

    h_in, w_in = img.shape[:2]
    best_idx = -1
    best_dist = float("inf")
    for i, m in enumerate(bin_masks):
        ys, xs = np.nonzero(m)
        if len(xs) == 0:
            continue
        cx = xs.mean() * (w_in / m.shape[1])
        cy = ys.mean() * (h_in / m.shape[0])
        d = (cx - target_cx) ** 2 + (cy - target_cy) ** 2
        if d < best_dist:
            best_dist = d
            best_idx = i

    if best_idx < 0:
        return None
    # Scale mask area to original-image pixels.
    m = bin_masks[best_idx]
    scale = (h_in / m.shape[0]) * (w_in / m.shape[1])
    return float(m.sum() * scale)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Path to YOLOv8-seg best.pt")
    parser.add_argument("--weights-csv", required=True, help="Per-bird weights CSV")
    parser.add_argument("--images-dir", required=True, help="Directory of photos")
    parser.add_argument("--output", default="regression.json", help="Output JSON")
    args = parser.parse_args()

    try:
        from ultralytics import YOLO
        from sklearn.linear_model import LinearRegression
        from sklearn.metrics import mean_absolute_error, r2_score
        import numpy as np
    except ImportError as exc:
        print(f"Missing dep: {exc}. Install: pip install ultralytics scikit-learn", file=sys.stderr)
        return 1

    samples = _load_csv(Path(args.weights_csv), Path(args.images_dir))
    if not samples:
        print("No samples loaded — check CSV + images path.", file=sys.stderr)
        return 1
    print(f"Loaded {len(samples)} weighed-chicken samples.")

    print(f"Loading model: {args.model}")
    model = YOLO(args.model)

    areas: list[float] = []
    weights: list[float] = []
    skipped = 0
    for s in samples:
        area = _mask_area_for_sample(model, s)
        if area is None or area <= 0:
            skipped += 1
            print(f"  skip (no mask): {s.image.name}")
            continue
        areas.append(area)
        weights.append(s.weight_g)
        print(f"  {s.image.name}: mask_area={area:.0f} px, weight={s.weight_g} g")

    if len(areas) < 5:
        print(f"Only {len(areas)} usable samples ({skipped} skipped). Need at least 5.",
              file=sys.stderr)
        return 1

    # Camera-invariant baseline = median area in the dataset. Production should
    # pass per-camera ref_area_px values; for a single-camera calibration this
    # is reasonable.
    ref_area_px = float(np.median(areas))
    normalized = np.array(areas) / ref_area_px
    y = np.array(weights)

    reg = LinearRegression().fit(normalized.reshape(-1, 1), y)
    slope = float(reg.coef_[0])
    intercept = float(reg.intercept_)

    y_pred = reg.predict(normalized.reshape(-1, 1))
    r2 = float(r2_score(y, y_pred))
    mae = float(mean_absolute_error(y, y_pred))

    out = {
        "slope": round(slope, 4),
        "intercept": round(intercept, 4),
        "ref_area_px": round(ref_area_px, 2),
        "n_samples": len(areas),
        "n_skipped": skipped,
        "r2": round(r2, 4),
        "mae_g": round(mae, 2),
    }

    Path(args.output).write_text(json.dumps(out, indent=2))
    print()
    print(f"✓ Fitted regression on {len(areas)} samples")
    print(f"  slope:      {slope:+.4f}")
    print(f"  intercept:  {intercept:+.2f}")
    print(f"  ref_area:   {ref_area_px:.0f} px")
    print(f"  R²:         {r2:.3f}     (1.0 = perfect)")
    print(f"  MAE:        {mae:.1f} g   (avg per-bird error in grams)")
    print()
    print(f"Saved → {args.output}")
    print()
    print("Paste into models/weight-estimator/0.4.0-mask-area/metadata.json:")
    print(json.dumps(
        {
            "regression": {"slope": round(slope, 4), "intercept": round(intercept, 4)},
            "camera_calibration": {
                "<camera_id>": {"ref_area_px": round(ref_area_px, 2)}
            },
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
