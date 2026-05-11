"""Heuristic weight estimator — breed/age lookup with linear interpolation.

This is a calibration baseline, not real CV. It exists to:
  1. Wire the WeightEstimate event end-to-end before we have labeled samples.
  2. Give the cloud something realistic to chart while v1.0.0 (regression) is
     being trained.

Growth curves come from `metadata.json` so a new breed is a config change, not
a code change. The model honestly reports low confidence (default 0.4 × the
detection confidence) so dashboards can deprioritize it once a real model lands.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection, WeightEstimate
from edge.inference.model_loader import ModelDescriptor

# Built-in fallback so the heuristic works even with empty metadata.
# Numbers are approximations of standard broiler curves (Ross 308, Cobb 500).
_BUILTIN_CURVES: dict[str, list[tuple[int, float]]] = {
    "ross_308": [
        (1, 42), (7, 180), (14, 480), (21, 980), (28, 1620), (35, 2350), (42, 3050),
    ],
    "cobb_500": [
        (1, 42), (7, 175), (14, 460), (21, 950), (28, 1580), (35, 2300), (42, 3000),
    ],
}
_DEFAULT_BREED = "ross_308"


class HeuristicWeightEstimator:
    def __init__(self, descriptor: ModelDescriptor) -> None:
        self._descriptor = descriptor
        meta = descriptor.metadata
        raw_curves = meta.get("growth_curves") or {}
        # Normalize: tolerate JSON's [[age, weight], ...] form.
        self._curves: dict[str, list[tuple[int, float]]] = {
            self._normalize_breed(name): [(int(a), float(w)) for a, w in points]
            for name, points in raw_curves.items()
        } or dict(_BUILTIN_CURVES)
        self._default_breed = self._normalize_breed(meta.get("default_breed", _DEFAULT_BREED))
        self._baseline_confidence = float(meta.get("baseline_confidence", 0.4))

    @property
    def model_version(self) -> str:
        return self._descriptor.reference

    async def start(self) -> None:
        # No expensive setup; declared for parity with YoloBirdDetector so the
        # supervisor calls it uniformly.
        return None

    async def estimate(
        self,
        frame: Frame,
        detection: BirdDetection,
        bird_age_days: int | None = None,
        breed: str | None = None,
    ) -> WeightEstimate:
        curve = self._curve_for(breed)
        if not curve or bird_age_days is None:
            estimated = 0.0
            confidence = 0.0
        else:
            estimated = self._interpolate(curve, bird_age_days)
            confidence = round(self._baseline_confidence * detection.confidence, 4)

        return WeightEstimate(
            device_id="",  # filled in by the pipeline
            camera_id=frame.camera_id,
            shed_id=detection.shed_id,
            flock_id=detection.flock_id,
            captured_at=frame.captured_at,
            processed_at=datetime.now(timezone.utc),
            model_version=self.model_version,
            estimated_avg_weight_g=round(estimated, 1),
            confidence=confidence,
            sample_size=detection.bird_count,
            bird_age_days=bird_age_days,
            breed=breed,
        )

    # ── internal ───────────────────────────────────────────────────────────
    def _curve_for(self, breed: str | None) -> list[tuple[int, float]]:
        if breed:
            curve = self._curves.get(self._normalize_breed(breed))
            if curve:
                return curve
        return self._curves.get(self._default_breed) or []

    @staticmethod
    def _normalize_breed(name: Any) -> str:
        return str(name).strip().lower().replace(" ", "_").replace("-", "_")

    @staticmethod
    def _interpolate(curve: list[tuple[int, float]], age: int) -> float:
        """Linear interpolation between (age_days, weight_g) points; clamps at ends."""
        sorted_curve = sorted(curve)
        if age <= sorted_curve[0][0]:
            return float(sorted_curve[0][1])
        if age >= sorted_curve[-1][0]:
            return float(sorted_curve[-1][1])
        for (a1, w1), (a2, w2) in zip(sorted_curve, sorted_curve[1:], strict=True):
            if a1 <= age <= a2:
                t = (age - a1) / (a2 - a1)
                return w1 + (w2 - w1) * t
        return float(sorted_curve[-1][1])  # unreachable
