"""Hot-swappable huddling detector — same registry+proxy pattern."""

from __future__ import annotations

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection, HuddlingScore
from edge.inference.inference import HuddlingDetector


class HuddlingRegistry:
    """Holds the active huddling detector. Atomic swap on model change."""

    def __init__(self, initial: HuddlingDetector) -> None:
        self._current: HuddlingDetector = initial

    @property
    def current(self) -> HuddlingDetector:
        return self._current

    def swap(self, new: HuddlingDetector) -> HuddlingDetector:
        old, self._current = self._current, new
        return old


class ProxiedHuddlingDetector:
    """HuddlingDetector facade that always delegates to `registry.current`."""

    def __init__(self, registry: HuddlingRegistry) -> None:
        self._registry = registry

    @property
    def model_version(self) -> str:
        return self._registry.current.model_version

    async def score(self, frame: Frame, detection: BirdDetection) -> HuddlingScore:
        return await self._registry.current.score(frame, detection)
