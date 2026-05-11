"""Factory: ModelDescriptor → BirdDetector adapter.

Picks the right concrete adapter (stub vs YOLO) based on the descriptor.
Adding a new adapter (e.g. a Triton-served model) is a one-line change here.
"""

from __future__ import annotations

from edge.inference.inference import BirdDetector
from edge.inference.model_loader import ModelDescriptor


def build_bird_detector(descriptor: ModelDescriptor) -> BirdDetector:
    """Pick the right adapter based on descriptor type."""
    if descriptor.is_stub:
        # Lazy import to keep stub usage free of YOLO/onnxruntime deps.
        from edge.inference.models.stub_detector import StubBirdDetector  # noqa: PLC0415

        return StubBirdDetector(model_version=descriptor.reference)

    # Real ONNX-backed detector — only imported when actually needed.
    from edge.inference.models.bird_detector import YoloBirdDetector  # noqa: PLC0415

    return YoloBirdDetector(descriptor)
