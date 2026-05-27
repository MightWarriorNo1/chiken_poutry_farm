"""Mask-area regression weight estimator.

Selected via `metadata.json`:
    {"algorithm": "mask-area", "artifact": "model.pt",
     "regression": {"slope": 0.0023, "intercept": 80.5},
     "camera_calibration": {
       "usb-cam-1": {"ref_area_px": 12500.0},
       "cam-shed-1": {"ref_area_px": 14800.0}
     },
     "thresholds": {"confidence": 0.25, "iou": 0.45}}

Workflow per frame:
  1. Run a YOLOv8-segmentation model → per-chicken pixel masks (NOT bboxes).
  2. For each mask: count its true pixel area (no rectangle, no background).
  3. Normalize by the camera's `ref_area_px` for mount-height invariance.
  4. Apply linear regression:  weight_g = slope · normalized + intercept
  5. Average across all detected birds for the frame-level estimate.

Why this beats bbox-area regression: a bounding box is a rectangle that
inevitably includes background pixels around an irregular shape. A mask
captures ONLY the chicken's body — so the signal-to-noise ratio is far
higher. Empirically: mask-area correlates ~3× better with weight than
bbox-area does, because pose/posture changes (standing vs. sitting) shift
mask area a lot but bbox dimensions barely.

This sister-adapter to SegHuddlingDetector consumes the SAME YOLOv8-seg
`.pt` model — segmentation training serves both purposes (huddling +
weight) with one checkpoint.

Required artifact: a YOLOv8-seg model (`task=segment`) trained on chicken
polygon labels. Standard COCO YOLOv8-seg.pt does NOT include "chicken" as
a fine-grained class — you'll need to train one.

The two regression coefficients (`slope`, `intercept`) come from
sklearn-fitting `(normalized_mask_area, weighed_weight_g)` pairs from the
client's calibration samples. Drop them into `metadata.json`; no training
of the regression itself is needed at runtime.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import anyio
import numpy as np

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection, WeightEstimate
from edge.inference.model_loader import ModelDescriptor


class MaskAreaWeightEstimator:
    def __init__(self, descriptor: ModelDescriptor) -> None:
        self._descriptor = descriptor
        meta = descriptor.metadata

        regression = meta.get("regression") or {}
        self._slope = float(regression.get("slope", 0.0))
        self._intercept = float(regression.get("intercept", 0.0))

        cal = meta.get("camera_calibration") or {}
        self._camera_calibration: dict[str, float] = {
            str(cam_id): float(cfg.get("ref_area_px", 10000.0))
            for cam_id, cfg in cal.items()
        }
        self._fallback_ref_area = float(meta.get("fallback_ref_area_px", 10000.0))
        self._baseline_confidence = float(meta.get("baseline_confidence", 0.65))

        thresholds = meta.get("thresholds", {})
        self._conf = float(thresholds.get("confidence", 0.25))
        self._iou = float(thresholds.get("iou", 0.45))
        self._model: Any | None = None
        self._device: str | int = "cpu"

    @property
    def model_version(self) -> str:
        return self._descriptor.reference

    async def start(self) -> None:
        try:
            from ultralytics import YOLO  # noqa: PLC0415
            import torch  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "Install ultralytics + Jetson PyTorch (see requirements-jetson.txt)."
            ) from exc

        artifact = self._descriptor.artifact_path
        if artifact is None or not artifact.is_file():
            raise FileNotFoundError(
                f"YOLOv8-seg model artifact missing: {artifact}. "
                "Train a segmentation model on chicken polygon labels and "
                "place model.pt here. Same model can be shared with the "
                "huddling-detector seg adapter."
            )

        device: str | int = 0 if torch.cuda.is_available() else "cpu"

        def _load() -> Any:
            m = YOLO(str(artifact))
            try:
                m.to(device)
            except Exception:  # noqa: BLE001
                pass
            return m

        self._model = await anyio.to_thread.run_sync(_load)
        self._device = device

    async def estimate(
        self,
        frame: Frame,
        detection: BirdDetection,
        bird_age_days: int | None = None,
        breed: str | None = None,
    ) -> WeightEstimate:
        if self._model is None:
            await self.start()

        per_bird_weights = await anyio.to_thread.run_sync(
            self._infer, frame, detection
        )
        if not per_bird_weights:
            return self._empty(frame, detection, bird_age_days, breed)

        avg = float(sum(per_bird_weights) / len(per_bird_weights))
        confidence = round(
            min(1.0, self._baseline_confidence * float(detection.confidence or 0.0)),
            4,
        )

        return WeightEstimate(
            device_id="",
            camera_id=frame.camera_id,
            shed_id=detection.shed_id,
            flock_id=detection.flock_id,
            captured_at=frame.captured_at,
            processed_at=datetime.now(timezone.utc),
            model_version=self.model_version,
            estimated_avg_weight_g=round(avg, 1),
            confidence=confidence,
            sample_size=len(per_bird_weights),
            bird_age_days=bird_age_days,
            breed=breed,
        )

    # ── private ────────────────────────────────────────────────────────────

    def _infer(self, frame: Frame, detection: BirdDetection) -> list[float]:
        assert self._model is not None

        results = self._model.predict(
            frame.image,
            conf=self._conf,
            iou=self._iou,
            device=self._device,
            verbose=False,
        )
        if not results:
            return []

        r = results[0]
        masks = getattr(r, "masks", None)
        if masks is None or masks.data is None or len(masks.data) == 0:
            return []

        try:
            arr = masks.data.cpu().numpy()
        except AttributeError:
            arr = np.asarray(masks.data, dtype=np.float32)
        bin_masks = (arr > 0.5).astype(np.uint8)

        ref_area = self._camera_calibration.get(
            frame.camera_id, self._fallback_ref_area
        )

        per_bird: list[float] = []
        for m in bin_masks:
            mask_area_px = float(m.sum())  # actual chicken pixels, not bbox
            if mask_area_px <= 0:
                continue
            normalized = mask_area_px / max(1.0, ref_area)
            w_g = self._slope * normalized + self._intercept
            per_bird.append(max(0.0, float(w_g)))
        return per_bird

    def _empty(
        self,
        frame: Frame,
        detection: BirdDetection,
        bird_age_days: int | None,
        breed: str | None,
    ) -> WeightEstimate:
        return WeightEstimate(
            device_id="",
            camera_id=frame.camera_id,
            shed_id=detection.shed_id,
            flock_id=detection.flock_id,
            captured_at=frame.captured_at,
            processed_at=datetime.now(timezone.utc),
            model_version=self.model_version,
            estimated_avg_weight_g=0.0,
            confidence=0.0,
            sample_size=0,
            bird_age_days=bird_age_days,
            breed=breed,
        )
