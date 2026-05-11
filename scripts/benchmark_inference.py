"""Benchmark bird-detector inference latency + throughput.

Useful for capacity planning ("how many cameras can a Jetson Orin Nano handle?")
and regression detection between model versions.

Usage:
    python scripts/benchmark_inference.py --version 1.0.0
    python scripts/benchmark_inference.py --version 1.0.0 --frames 500 --width 1920 --height 1080
"""

from __future__ import annotations

import argparse
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import anyio


async def amain(args: argparse.Namespace) -> int:
    try:
        import numpy as np  # noqa: PLC0415
    except ImportError:
        print("Install with: pip install -e '.[ai]'")
        return 1

    from edge.capture.source import Frame  # noqa: PLC0415
    from edge.inference.factory import build_bird_detector  # noqa: PLC0415
    from edge.inference.model_loader import ModelLoader  # noqa: PLC0415

    loader = ModelLoader(Path(args.models_root))
    descriptor = loader.load("bird-detector", args.version)
    detector = build_bird_detector(descriptor)

    start = getattr(detector, "start", None)
    if callable(start):
        await start()

    rng = np.random.default_rng(0)
    image = rng.integers(0, 255, (args.height, args.width, 3), dtype=np.uint8)
    frame = Frame(
        camera_id="bench",
        captured_at=datetime.now(timezone.utc),
        width=args.width,
        height=args.height,
        image=image,
    )

    print(f"Warming up ({args.warmup} runs)...")
    for _ in range(args.warmup):
        await detector.detect(frame)

    print(f"Benchmarking {args.frames} frames @ {args.width}×{args.height} ...")
    latencies_ms: list[float] = []
    t0 = time.perf_counter()
    for _ in range(args.frames):
        t = time.perf_counter()
        result = await detector.detect(frame)
        latencies_ms.append((time.perf_counter() - t) * 1000)
    elapsed = time.perf_counter() - t0

    print()
    print(f"Model:         {descriptor.reference}")
    print(f"Resolution:    {args.width}×{args.height}")
    print(f"Frames:        {args.frames}")
    print(f"Wall time:     {elapsed:.2f} s")
    print(f"Throughput:    {args.frames / elapsed:.2f} FPS")
    print(f"Latency p50:   {statistics.median(latencies_ms):.1f} ms")
    if len(latencies_ms) >= 20:
        print(f"Latency p95:   {statistics.quantiles(latencies_ms, n=20)[18]:.1f} ms")
    if len(latencies_ms) >= 100:
        print(f"Latency p99:   {statistics.quantiles(latencies_ms, n=100)[98]:.1f} ms")
    print(f"Last detection: {result.bird_count} birds, conf={result.confidence:.2f}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--version", default="1.0.0", help="Model version under models/bird-detector/")
    p.add_argument("--models-root", default="./models")
    p.add_argument("--frames", type=int, default=100)
    p.add_argument("--warmup", type=int, default=5)
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    args = p.parse_args()
    return anyio.run(amain, args)


if __name__ == "__main__":
    raise SystemExit(main())
