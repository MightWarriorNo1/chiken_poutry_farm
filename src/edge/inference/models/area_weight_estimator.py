"""Bbox-area regression weight estimator.

Selected via `metadata.json`:
    {"algorithm": "bbox-area",
     "regression": {"slope": 0.0023, "intercept": 120.5},
     "camera_calibration": {
       "usb-cam-1": {"ref_area_px": 18500.0},
       "cam-shed-1": {"ref_area_px": 22300.0}
     }}

Workflow per frame:
  1. For each detected chicken bounding box, compute its pixel area.
  2. Normalize by the camera's `ref_area_px` (accounts for mounting height /
     focal length — a chicken near the lens has a different pixel area than the
     same chicken far away).
  3. Apply linear regression:  weight_g = slope · normalized_area + intercept
  4. Average across all detected birds in the frame.

Inputs needed from somewhere outside this code:
  - `regression.slope` / `regression.intercept` — from sklearn LinearRegression
    fit on (normalized_area, known_weight_g) pairs.
  - `camera_calibration.<camera_id>.ref_area_px` — the bbox area of a
    reference-weight chicken in that specific camera. Mount-height-dependent.

Why this works as a layer over your existing YOLO: YOLO already detects boxes
on every frame. We're not running another model — just doing arithmetic on the
output. Marginal cost is ~5 µs per chicken.

Honest accuracy ceiling: ~±15% per bird. Bbox-area is a noisy proxy because:
  - Birds aren't seen from the same angle every frame
  - Pose (standing vs sitting) changes apparent area dramatically
  - Crowded birds get partially-occluded bboxes that under-area

Frame averaging smooths most of this. For better accuracy, see
`cnn_weight_estimator.py`.

This adapter does NOT need a separately-trained model file — `metadata.json`
carries everything. The "training" is: collect a handful of weight/area
samples (see scripts/train_area_regression.py if/when we write it), fit
sklearn LinearRegression once, paste the two numbers into metadata.json.
"""

from __future__ import annotations

from datetime import datetime, timezone

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection, WeightEstimate
from edge.inference.model_loader import ModelDescriptor


class AreaRegressionWeightEstimator:
    def __init__(self, descriptor: ModelDescriptor) -> None:
        self._descriptor = descriptor
        meta = descriptor.metadata

        regression = meta.get("regression") or {}
        self._slope = float(regression.get("slope", 0.0))
        self._intercept = float(regression.get("intercept", 0.0))

        # Per-camera reference area (in pixels) for normalization
        # against mount height + lens differences.
        cal = meta.get("camera_calibration") or {}
        self._camera_calibration: dict[str, float] = {
            str(cam_id): float(cfg.get("ref_area_px", 10000.0))
            for cam_id, cfg in cal.items()
        }
        self._fallback_ref_area = float(meta.get("fallback_ref_area_px", 10000.0))
        self._baseline_confidence = float(meta.get("baseline_confidence", 0.55))

    @property
    def model_version(self) -> str:
        return self._descriptor.reference

    async def start(self) -> None:
        return None  # pure arithmetic, nothing to load

    async def estimate(
        self,
        frame: Frame,
        detection: BirdDetection,
        bird_age_days: int | None = None,
        breed: str | None = None,
    ) -> WeightEstimate:
        if detection.bird_count == 0:
            return self._empty(frame, detection, bird_age_days, breed)

        ref_area = self._camera_calibration.get(
            frame.camera_id, self._fallback_ref_area
        )
        # If the detector populated per-bird boxes, predict per-bird and
        # average. This is the genuine size-based regression. Without boxes
        # we fall back to the frame-area / bird-count proxy (much weaker
        # signal — kept so legacy events still produce *something*).
        if detection.bboxes:
            frame_w = max(1, frame.width)
            frame_h = max(1, frame.height)
            per_bird_weights: list[float] = []
            for _cx, _cy, bw, bh in detection.bboxes:
                bbox_area_px = float(bw * bh) * frame_w * frame_h
                normalized = bbox_area_px / max(1.0, ref_area)
                w_g = self._slope * normalized + self._intercept
                per_bird_weights.append(max(0.0, float(w_g)))
            avg_weight = (
                sum(per_bird_weights) / len(per_bird_weights)
                if per_bird_weights
                else 0.0
            )
        else:
            frame_area = max(1, frame.width * frame.height)
            per_bird_area = frame_area / max(1, detection.bird_count)
            normalized = per_bird_area / max(1.0, ref_area)
            avg_weight = max(0.0, float(self._slope * normalized + self._intercept))

        # Per-frame confidence: scale by detection confidence and clamp.
        confidence = round(
            min(1.0, self._baseline_confidence * float(detection.confidence)), 4
        )

        return WeightEstimate(
            device_id="",
            camera_id=frame.camera_id,
            shed_id=detection.shed_id,
            flock_id=detection.flock_id,
            captured_at=frame.captured_at,
            processed_at=datetime.now(timezone.utc),
            model_version=self.model_version,
            estimated_avg_weight_g=round(avg_weight, 1),
            confidence=confidence,
            sample_size=detection.bird_count,
            bird_age_days=bird_age_days,
            breed=breed,
        )

    # ── internal ───────────────────────────────────────────────────────────

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
