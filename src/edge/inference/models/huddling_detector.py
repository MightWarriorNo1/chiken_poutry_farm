"""Huddling detector — DBSCAN over normalized bird centroids.

Birds that pile into tight clusters → high huddling score. Zone-aware via bbox split.
"""

from __future__ import annotations

from datetime import datetime, timezone

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection, HuddlingScore
from edge.inference.model_loader import ModelDescriptor


class DbscanHuddlingDetector:
    def __init__(
        self,
        descriptor: ModelDescriptor,
        eps: float = 0.05,        # neighborhood radius in normalized coords
        min_samples: int = 4,     # minimum birds for a cluster
    ) -> None:
        self._descriptor = descriptor
        self._eps = eps
        self._min_samples = min_samples

    @property
    def model_version(self) -> str:
        return self._descriptor.reference

    async def score(self, frame: Frame, detection: BirdDetection) -> HuddlingScore:
        # Sprint 5: real DBSCAN. Stub for scaffold.
        raise NotImplementedError("Huddling detection lands in Sprint 5.")

        return HuddlingScore(  # pragma: no cover
            device_id="",
            camera_id=frame.camera_id,
            shed_id=detection.shed_id,
            flock_id=detection.flock_id,
            zone_id=detection.zone_id,
            captured_at=frame.captured_at,
            processed_at=datetime.now(timezone.utc),
            model_version=self.model_version,
            huddling_score=0.0,
            cluster_count=0,
            largest_cluster_pct=0.0,
        )
