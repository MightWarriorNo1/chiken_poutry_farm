"""Weight estimator adapter.

PoC v0: a calibrated heuristic — projected pixel area per bird → grams via a breed/age
lookup. v1: regression model trained on labeled samples. The port doesn't change.
"""

from __future__ import annotations

from datetime import datetime, timezone

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection, WeightEstimate
from edge.inference.model_loader import ModelDescriptor


class HeuristicWeightEstimator:
    """Heuristic baseline. Replaceable by a regression model behind the same port."""

    def __init__(self, descriptor: ModelDescriptor) -> None:
        self._descriptor = descriptor

    @property
    def model_version(self) -> str:
        return self._descriptor.reference

    async def estimate(
        self,
        frame: Frame,
        detection: BirdDetection,
        bird_age_days: int | None = None,
        breed: str | None = None,
    ) -> WeightEstimate:
        # Sprint 4: real heuristic / regression. Stub for scaffold.
        raise NotImplementedError("Weight estimation logic lands in Sprint 4.")

        # Reference shape for when implemented:
        return WeightEstimate(  # pragma: no cover
            device_id="",
            camera_id=frame.camera_id,
            shed_id=detection.shed_id,
            flock_id=detection.flock_id,
            captured_at=frame.captured_at,
            processed_at=datetime.now(timezone.utc),
            model_version=self.model_version,
            estimated_avg_weight_g=0.0,
            confidence=0.0,
            sample_size=detection.bird_count,
            bird_age_days=bird_age_days,
            breed=breed,
        )
