"""Factories: ModelDescriptor → typed inference adapter.

One factory per port (BirdDetector, WeightEstimator, HuddlingDetector, ...).
Adding a new adapter is a one-branch change in the relevant factory.
"""

from __future__ import annotations

from edge.inference.inference import BirdDetector, HuddlingDetector, WeightEstimator
from edge.inference.model_loader import ModelDescriptor


def build_bird_detector(descriptor: ModelDescriptor) -> BirdDetector:
    """Pick the right BirdDetector adapter based on descriptor type.

    Selection order, falling through on missing optional deps:
      1. Stub (virtual descriptor)              — no artifact on disk
      2. TensorRT engine                        — `model.engine` next to `model.onnx`
                                                   AND `tensorrt` + `pycuda` importable
      3. PyTorch `.pt` checkpoint               — `UltralyticsBirdDetector`
                                                   (torch.cuda on Jetson when the
                                                   NVIDIA-built torch wheel is in venv)
      4. ONNX Runtime (CPU or CUDA EP)          — `model.onnx`
    """
    if descriptor.is_stub:
        # Lazy import to keep stub usage free of YOLO/onnxruntime deps.
        from edge.inference.models.stub_detector import StubBirdDetector  # noqa: PLC0415

        return StubBirdDetector(model_version=descriptor.reference)

    # Look for a sibling .engine and use the TRT detector if the runtime is
    # available on this machine (Jetson). Cleanly falls back to other paths.
    engine_path = _trt_engine_for(descriptor)
    if engine_path is not None and _trt_runtime_available():
        from edge.inference.models.trt_bird_detector import TRTBirdDetector  # noqa: PLC0415

        return TRTBirdDetector(descriptor, engine_path)

    # PyTorch checkpoint — use ultralytics. torch.cuda kicks in automatically
    # on Jetson when the NVIDIA-built torch wheel is installed.
    artifact = descriptor.artifact_path
    if artifact is not None and artifact.suffix.lower() == ".pt":
        from edge.inference.models.ultralytics_detector import (  # noqa: PLC0415
            UltralyticsBirdDetector,
        )

        return UltralyticsBirdDetector(descriptor)

    # Default: ONNX-backed detector (TensorRT/CUDA EPs when ORT-GPU is installed).
    from edge.inference.models.bird_detector import YoloBirdDetector  # noqa: PLC0415

    return YoloBirdDetector(descriptor)


def _trt_engine_for(descriptor: ModelDescriptor) -> object | None:
    """Return the path to `model.engine` in the descriptor's directory, or None."""
    artifact = descriptor.artifact_path
    if artifact is None:
        return None
    candidate = artifact.parent / "model.engine"
    return candidate if candidate.is_file() else None


def _trt_runtime_available() -> bool:
    """Return True iff `tensorrt` + `pycuda` can be imported (Jetson stack)."""
    try:
        import tensorrt  # noqa: F401, PLC0415
        import pycuda.driver  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True


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
