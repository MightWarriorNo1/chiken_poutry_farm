"""Ports for the three AI capabilities used in the PoC.

Adapters live in `edge.inference.models.*`. Each port is intentionally narrow so
swapping to a TensorRT/Triton implementation later is a one-file change.
"""

from __future__ import annotations

from typing import Protocol

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection, HuddlingScore, WeightEstimate


class BirdDetector(Protocol):
    """Detect birds and produce a BirdDetection event for a single frame."""

    model_version: str

    async def detect(self, frame: Frame) -> BirdDetection: ...


class WeightEstimator(Protocol):
    """Estimate average flock weight from a frame (and prior detections)."""

    model_version: str

    async def estimate(
        self,
        frame: Frame,
        detection: BirdDetection,
        bird_age_days: int | None = None,
        breed: str | None = None,
    ) -> WeightEstimate: ...


class HuddlingDetector(Protocol):
    """Compute a huddling score from bird positions in the frame."""

    model_version: str

    async def score(self, frame: Frame, detection: BirdDetection) -> HuddlingScore: ...
