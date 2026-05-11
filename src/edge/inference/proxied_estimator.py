"""Hot-swappable weight estimator — same registry+proxy pattern as the detector.

We keep the two registries separate (rather than a generic `Registry[T]`) because
each port has its own method shape (`detect` vs `estimate`) and the runtime cost
of a tiny dedicated proxy class is zero.
"""

from __future__ import annotations

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection, WeightEstimate
from edge.inference.inference import WeightEstimator


class EstimatorRegistry:
    """Holds the active weight estimator. Atomic swap on model change."""

    def __init__(self, initial: WeightEstimator) -> None:
        self._current: WeightEstimator = initial

    @property
    def current(self) -> WeightEstimator:
        return self._current

    def swap(self, new: WeightEstimator) -> WeightEstimator:
        old, self._current = self._current, new
        return old


class ProxiedWeightEstimator:
    """WeightEstimator facade that always delegates to `registry.current`."""

    def __init__(self, registry: EstimatorRegistry) -> None:
        self._registry = registry

    @property
    def model_version(self) -> str:
        return self._registry.current.model_version

    async def estimate(
        self,
        frame: Frame,
        detection: BirdDetection,
        bird_age_days: int | None = None,
        breed: str | None = None,
    ) -> WeightEstimate:
        return await self._registry.current.estimate(frame, detection, bird_age_days, breed)
