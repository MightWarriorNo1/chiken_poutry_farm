"""Stub huddling detector — emits a low constant score for plumbing demos."""

from __future__ import annotations

from datetime import datetime, timezone

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection, HuddlingScore


class StubHuddlingDetector:
    def __init__(self, model_version: str = "huddling-detector@stub-0.0.1") -> None:
        self._model_version = model_version

    @property
    def model_version(self) -> str:
        return self._model_version

    async def score(self, frame: Frame, detection: BirdDetection) -> HuddlingScore:
        return HuddlingScore(
            device_id="",  # filled in by the pipeline
            camera_id=frame.camera_id,
            shed_id=detection.shed_id,
            flock_id=detection.flock_id,
            zone_id=detection.zone_id,
            captured_at=frame.captured_at,
            processed_at=datetime.now(timezone.utc),
            model_version=self._model_version,
            huddling_score=0.1,        # low + constant — distinguishable from real signal
            cluster_count=0,
            largest_cluster_pct=0.0,
        )
