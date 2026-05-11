"""Stub weight estimator — emits a fixed visible value at low confidence.

Mirrors `StubBirdDetector`: lets demos run end-to-end before the heuristic or a
real CV model is wired up. The fixed value is non-zero so it shows up on the
dashboard, but `confidence=0.05` makes it obvious downstream that this is not
a real measurement.
"""

from __future__ import annotations

from datetime import datetime, timezone

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection, WeightEstimate


class StubWeightEstimator:
    def __init__(
        self,
        model_version: str = "weight-estimator@stub-0.0.1",
        fixed_weight_g: float = 1500.0,
    ) -> None:
        self._model_version = model_version
        self._fixed = fixed_weight_g

    @property
    def model_version(self) -> str:
        return self._model_version

    async def estimate(
        self,
        frame: Frame,
        detection: BirdDetection,
        bird_age_days: int | None = None,
        breed: str | None = None,
    ) -> WeightEstimate:
        return WeightEstimate(
            device_id="",  # filled in by the pipeline
            camera_id=frame.camera_id,
            shed_id=detection.shed_id,
            flock_id=detection.flock_id,
            captured_at=frame.captured_at,
            processed_at=datetime.now(timezone.utc),
            model_version=self._model_version,
            estimated_avg_weight_g=self._fixed,
            confidence=0.05,
            sample_size=detection.bird_count,
            bird_age_days=bird_age_days,
            breed=breed,
        )
