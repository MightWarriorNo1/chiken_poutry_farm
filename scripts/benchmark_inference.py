"""Benchmark YOLO bird-detector inference on the current host.

Generates synthetic frames, warms up the session, then times N inferences. Prints
the FPS and per-frame latency the edge can sustain on this hardware. Use the same
script on dev laptop, Jetson, and production hardware for comparable numbers.

Usage:
    python scripts/benchmark_inference.py
    python scripts/benchmark_inference.py --version v1.0.0 --iterations 200
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

import anyio


async def amain(args: argparse.Namespace) -> int:
    try:
        import numpy as np  # noqa: PLC0415
    except ImportError:
        print("Install with: pip install -e '.[ai]'")
        return 1

    from edge.capture.source import Frame  # noqa: PLC0415
    from edge.inference.model_loader import ModelLoader  # noqa: PLC0415
    from edge.inference.models.bird_detector import YoloBirdDetector  # noqa: PLC0415

    descriptor = ModelLoader().load("bird-detector", args.version)
    detector = YoloBirdDetector(descriptor)
    await detector.start()

    rng = np.random.default_rng(seed=0)
    image = rng.integers(0, 256, size=(args.height, args.width, 3), dtype=np.uint8)
    frame = Frame(
        camera_id="bench",
        captured_at=datetime.now(timezone.utc),
        width=args.width,
        height=args.height,
        image=image,
    )

    print(f"Warmup ({args.warmup} iterations)...")
    for _ in range(args.warmup):
        await detector.detect(frame)

    print(f"Running benchmark ({args.iterations} iterations)...")
    started = time.perf_counter()
    for _ in range(args.iterations):
        await detector.detect(frame)
    elapsed = time.perf_counter() - started

    fps = args.iterations / elapsed
    per_ms = (elapsed / args.iterations) * 1000.0
    print()
    print(f"  model:       {detector.model_version}")
    print(f"  resolution:  {args.width}x{args.height}")
    print(f"  total:       {elapsed:.2f}s for {args.iterations} frames")
    print(f"  throughput:  {fps:.1f} FPS")
    print(f"  latency:     {per_ms:.1f} ms / frame")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="v1.0.0")
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args()
    return anyio.run(amain, args)


if __name__ == "__main__":
    raise SystemExit(main())
