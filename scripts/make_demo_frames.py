"""Generate synthetic poultry-shed-ish frames for offline development.

These look nothing like real chickens — they're just colored blobs on a brown
background — but they're enough to exercise the capture → outbox → sync flow.

Usage:
    python scripts/make_demo_frames.py --out ./demo/frames --count 10
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True, help="Output directory.")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--birds", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    try:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
    except ImportError:
        print("Install with: pip install -e '.[ai]'  (needs cv2 + numpy)")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    bg = np.full((args.height, args.width, 3), (90, 110, 130), dtype=np.uint8)

    for i in range(args.count):
        frame = bg.copy()
        # speckle the floor
        noise = (np.random.default_rng(args.seed + i).integers(-20, 20, frame.shape)).astype(np.int16)
        frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        for _ in range(args.birds):
            x = rng.randint(20, args.width - 20)
            y = rng.randint(20, args.height - 20)
            r = rng.randint(8, 14)
            color = (
                rng.randint(220, 255),
                rng.randint(220, 250),
                rng.randint(210, 245),
            )
            cv2.circle(frame, (x, y), r, color, thickness=-1)

        out_path = args.out / f"frame_{i:04d}.png"
        cv2.imwrite(str(out_path), frame)

    print(f"Wrote {args.count} frames to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
