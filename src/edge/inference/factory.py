"""Factories: ModelDescriptor → typed inference adapter.

One factory per port (BirdDetector, WeightEstimator, HuddlingDetector, ...).
Adding a new adapter is a one-branch change in the relevant factory.
"""

from __future__ import annotations

from edge.inference.inference import BirdDetector, HuddlingDetector, WeightEstimator
from edge.inference.model_loader import ModelDescriptor


def build_bird_detector(descriptor: ModelDescriptor) -> BirdDetector:
    """Pick the right BirdDetector adapter based on descriptor type."""
    if descriptor.is_stub:
        # Lazy import to keep stub usage free of YOLO/onnxruntime deps.
        from edge.inference.models.stub_detector import StubBirdDetector  # noqa: PLC0415

        return StubBirdDetector(model_version=descriptor.reference)

    # Real ONNX-backed detector — only imported when actually needed.
    from edge.inference.models.bird_detector import YoloBirdDetector  # noqa: PLC0415

    return YoloBirdDetector(descriptor)


def build_weight_estimator(descriptor: ModelDescriptor) -> WeightEstimator:
    """Pick the right WeightEstimator adapter based on descriptor type."""
    if descriptor.is_stub:
        from edge.inference.models.stub_weight_estimator import (  # noqa: PLC0415
            StubWeightEstimator,
        )

        return StubWeightEstimator(model_version=descriptor.reference)

    from edge.inference.models.weight_estimator import (  # noqa: PLC0415
        HeuristicWeightEstimator,
    )

    return HeuristicWeightEstimator(descriptor)


def build_huddling_detector(descriptor: ModelDescriptor) -> HuddlingDetector:
    """Pick the right HuddlingDetector adapter based on descriptor type."""
    if descriptor.is_stub:
        from edge.inference.models.stub_huddling import StubHuddlingDetector  # noqa: PLC0415

        return StubHuddlingDetector(model_version=descriptor.reference)

    from edge.inference.models.huddling_detector import (  # noqa: PLC0415
        DbscanHuddlingDetector,
    )

    return DbscanHuddlingDetector(descriptor)
