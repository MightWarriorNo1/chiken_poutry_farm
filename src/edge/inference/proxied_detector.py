"""Hot-swappable detector via a tiny registry + proxy facade.

Why this exists: the InferenceSupervisor wants to swap the active detector when
the cloud promotes a new model version, but FramePipelines hold a long-lived
reference to "the bird detector". The proxy lets pipelines stay oblivious to
swaps — they always call `proxy.detect(frame)`, which forwards to whatever the
registry currently points at.
"""

from __future__ import annotations

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection
from edge.inference.inference import BirdDetector


class DetectorRegistry:
    """Holds the active bird detector. Atomic swap on model change."""

    def __init__(self, initial: BirdDetector) -> None:
        self._current: BirdDetector = initial

    @property
    def current(self) -> BirdDetector:
        return self._current

    def swap(self, new: BirdDetector) -> BirdDetector:
        """Replace the active detector. Returns the previous one (for cleanup)."""
        old, self._current = self._current, new
        return old


class ProxiedBirdDetector:
    """BirdDetector facade that always delegates to `registry.current`.

    Implements the BirdDetector Protocol structurally so FramePipeline can hold
    a stable reference across model swaps.
    """

    def __init__(self, registry: DetectorRegistry) -> None:
        self._registry = registry

    @property
    def model_version(self) -> str:
        return self._registry.current.model_version

    async def detect(self, frame: Frame) -> BirdDetection:
        return await self._registry.current.detect(frame)
