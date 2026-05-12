"""Compile a YOLOv8n ONNX → TensorRT engine on the Jetson.

Run this once per device, per model version. The engine is GPU-arch specific
(Orin Nano is sm_87) — engines built on a workstation will NOT load on the
Jetson and vice versa.

Usage (on the device):

    python scripts/compile_yolo_trt.py
        --onnx models/bird-detector/v1.0.0/model.onnx
        --engine models/bird-detector/v1.0.0/model.engine
        --fp16

Defaults match the layout `download_yolov8n.py` produces.

Once the .engine file exists alongside the .onnx, the inference factory
auto-selects [TRTBirdDetector](../src/edge/inference/models/trt_bird_detector.py)
on the next start.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onnx", type=Path, default=Path("models/bird-detector/v1.0.0/model.onnx"))
    parser.add_argument(
        "--engine", type=Path, default=Path("models/bird-detector/v1.0.0/model.engine")
    )
    parser.add_argument("--fp16", action="store_true", default=True, help="(default) FP16 build")
    parser.add_argument("--fp32", action="store_true", help="Disable FP16 — slower, larger")
    parser.add_argument("--workspace", type=int, default=2048, help="MiB of TRT workspace")
    parser.add_argument(
        "--trtexec",
        type=str,
        default=None,
        help="Path to trtexec (auto-detected from /usr/src/tensorrt/bin if not set)",
    )
    args = parser.parse_args()

    if not args.onnx.is_file():
        print(f"ERROR: ONNX not found: {args.onnx}", file=sys.stderr)
        print("Run `python scripts/download_yolov8n.py` first.", file=sys.stderr)
        return 2

    trtexec = args.trtexec or _find_trtexec()
    if not trtexec:
        print(
            "ERROR: `trtexec` not found. JetPack normally puts it at "
            "/usr/src/tensorrt/bin/trtexec — pass --trtexec /path/to/trtexec.",
            file=sys.stderr,
        )
        return 2

    args.engine.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        trtexec,
        f"--onnx={args.onnx}",
        f"--saveEngine={args.engine}",
        f"--memPoolSize=workspace:{args.workspace}",
    ]
    if not args.fp32:
        cmd.append("--fp16")

    print("Running:", " ".join(cmd))
    print("This takes ~30–90s on Orin Nano. Sit tight.")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"\nERROR: trtexec failed with exit code {result.returncode}", file=sys.stderr)
        return result.returncode

    size_mb = args.engine.stat().st_size / 1024 / 1024
    print(f"\n✓ Engine: {args.engine}  ({size_mb:.1f} MB)")
    print("✓ Restart prosper-edge to pick up the new engine.")
    return 0


def _find_trtexec() -> str | None:
    """Look in the JetPack-standard place, then $PATH."""
    standard = Path("/usr/src/tensorrt/bin/trtexec")
    if standard.is_file():
        return str(standard)
    found = shutil.which("trtexec")
    return found


if __name__ == "__main__":
    raise SystemExit(main())
