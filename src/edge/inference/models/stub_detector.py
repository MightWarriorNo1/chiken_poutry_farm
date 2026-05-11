"""Stub bird detector for plumbing tests and offline demos.

Emits a deterministic-ish BirdDetection without any model file or framework. Useful
before YOLO lands in Sprint 2 — lets the full pipeline (capture → outbox → cloud)
run end-to-end against the contract.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection


class StubBirdDetector:
    """Returns synthetic but schema-valid detections."""

    def __init__(
        self,
        model_version: str = "bird-detector@stub-0.0.1",
        seed: int | None = None,
        min_birds: int = 60,
        max_birds: int = 140,
    ) -> None:
        self._model_version = model_version
        self._rng = random.Random(seed)
        self._min = min_birds
        self._max = max_birds

    @property
    def model_version(self) -> str:
        return self._model_version

    async def detect(self, frame: Frame) -> BirdDetection:
        n = self._rng.randint(self._min, self._max)
        centroids: list[tuple[float, float]] = [
            (self._rng.random(), self._rng.random()) for _ in range(n)
        ]
        return BirdDetection(
            device_id="",  # filled in by the pipeline
            camera_id=frame.camera_id,
            captured_at=frame.captured_at,
            processed_at=datetime.now(timezone.utc),
            model_version=self._model_version,
            bird_count=n,
            # Saturating curve so very dense scenes pin near 1.0.
            density_score=min(1.0, n / 150.0),
            confidence=round(self._rng.uniform(0.72, 0.94), 3),
            bbox_centroids=centroids,
        )
