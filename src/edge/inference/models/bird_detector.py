"""YOLO-based bird detector adapter.

The PoC bootstraps with the COCO `bird` class from a pretrained YOLOv8n.
Production fine-tunes on poultry-specific data; the adapter shape stays the same.
"""

from __future__ import annotations

from datetime import datetime, timezone

import anyio
import numpy as np

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection
from edge.inference.model_loader import ModelDescriptor

# COCO class id for bird (used as PoC stand-in until a poultry-specific model exists).
COCO_BIRD_CLASS_ID = 14


class YoloBirdDetector:
    """OpenCV+ONNXRuntime-backed bird detector.

    Stub implementation: load the model on `start()`, run inference per frame.
    Real inference logic lands in Sprint 2 — left as `_run_inference` to keep the
    integration surface (ports, pipelines) stable now.
    """

    def __init__(
        self,
        descriptor: ModelDescriptor,
        confidence_threshold: float = 0.25,
    ) -> None:
        self._descriptor = descriptor
        self._threshold = confidence_threshold
        self._session: object | None = None

    @property
    def model_version(self) -> str:
        return self._descriptor.reference

    async def start(self) -> None:
        # Lazy import so importing this module doesn't require onnxruntime at scaffold time.
        try:
            import onnxruntime as ort  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "Install the `ai` extra: pip install -e '.[ai]'"
            ) from exc

        def _create() -> object:
            return ort.InferenceSession(
                str(self._descriptor.artifact_path),
                providers=["CPUExecutionProvider"],
            )

        self._session = await anyio.to_thread.run_sync(_create)

    async def detect(self, frame: Frame) -> BirdDetection:
        if self._session is None:
            await self.start()

        bird_count, confidence, centroids = await anyio.to_thread.run_sync(
            self._run_inference, frame.image
        )
        density = self._density_score(bird_count, frame.width, frame.height)

        return BirdDetection(
            device_id="",  # filled in by the pipeline
            camera_id=frame.camera_id,
            captured_at=frame.captured_at,
            processed_at=datetime.now(timezone.utc),
            model_version=self.model_version,
            bird_count=bird_count,
            density_score=density,
            confidence=confidence,
            bbox_centroids=centroids,
        )

    # ── private ────────────────────────────────────────────────────────────
    def _run_inference(self, image: np.ndarray) -> tuple[int, float, list[tuple[float, float]]]:
        """Real YOLO inference lands here in Sprint 2.

        Returns (bird_count, mean_confidence, normalized_centroids).
        """
        # Sprint 0 placeholder: deterministic stub so pipeline tests can run.
        # Sprint 2 will replace with: preprocess -> session.run -> postprocess.
        raise NotImplementedError("YOLO inference lands in Sprint 2.")

    @staticmethod
    def _density_score(bird_count: int, w: int, h: int) -> float:
        # Birds per megapixel, clamped to [0, 1] with a soft saturation curve.
        # Tunable per-camera once we have ground truth.
        if w <= 0 or h <= 0:
            return 0.0
        per_mp = bird_count / ((w * h) / 1_000_000)
        return float(min(1.0, per_mp / 50.0))  # 50 birds/MP saturates the score
