"""DBSCAN-based huddling detector.

Clusters the normalized bird centroids that the bird detector already produces,
then reports:
  - `huddling_score`     = largest cluster fraction (0 = spread, 1 = one big blob)
  - `cluster_count`      = number of clusters found
  - `largest_cluster_pct`= same as huddling_score; kept separate so the cloud can
                           combine signals (e.g. many small clusters vs one panic blob)

Tuning knobs (metadata.json):
  - `eps`           radius in normalized [0, 1] image coords
  - `min_samples`   minimum birds for a cluster to count
  - `zone_overrides`  per-zone overrides for both params

Why DBSCAN and not k-means? We don't know how many clusters exist ahead of time,
and density-based clustering matches the physical reality: huddling is birds
packing tightly into a single dense region.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import anyio
import numpy as np

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection, HuddlingScore
from edge.inference.model_loader import ModelDescriptor


class DbscanHuddlingDetector:
    def __init__(self, descriptor: ModelDescriptor) -> None:
        self._descriptor = descriptor
        meta = descriptor.metadata
        self._eps = float(meta.get("eps", 0.05))
        self._min_samples = int(meta.get("min_samples", 4))
        self._zone_overrides: dict[str, dict[str, Any]] = meta.get("zone_overrides") or {}

    @property
    def model_version(self) -> str:
        return self._descriptor.reference

    async def start(self) -> None:
        # Verify sklearn is available eagerly so a bad install fails at swap time,
        # not on the first frame.
        try:
            from sklearn.cluster import DBSCAN  # noqa: F401, PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "Install the `ai` extra: pip install -e '.[ai]'"
            ) from exc

    async def score(self, frame: Frame, detection: BirdDetection) -> HuddlingScore:
        eps, min_samples = self._params_for_zone(detection.zone_id)
        centroids = detection.bbox_centroids

        if not centroids or len(centroids) < min_samples:
            return self._empty(frame, detection)

        return await anyio.to_thread.run_sync(
            self._compute, frame, detection, eps, min_samples
        )

    # ── private ───────────────────────────────────────────────────────────
    def _compute(
        self,
        frame: Frame,
        detection: BirdDetection,
        eps: float,
        min_samples: int,
    ) -> HuddlingScore:
        from sklearn.cluster import DBSCAN  # noqa: PLC0415

        pts = np.asarray(detection.bbox_centroids, dtype=np.float32)
        labels = DBSCAN(eps=eps, min_samples=min_samples).fit(pts).labels_

        n_total = len(pts)
        unique = {int(c) for c in labels.tolist() if c != -1}
        cluster_count = len(unique)

        if cluster_count == 0:
            largest_pct = 0.0
        else:
            largest_size = max(int((labels == c).sum()) for c in unique)
            largest_pct = largest_size / n_total

        return HuddlingScore(
            device_id="",  # filled in by the pipeline
            camera_id=frame.camera_id,
            shed_id=detection.shed_id,
            flock_id=detection.flock_id,
            zone_id=detection.zone_id,
            captured_at=frame.captured_at,
            processed_at=datetime.now(timezone.utc),
            model_version=self.model_version,
            huddling_score=round(largest_pct, 4),
            cluster_count=cluster_count,
            largest_cluster_pct=round(largest_pct, 4),
        )

    def _params_for_zone(self, zone_id: str | None) -> tuple[float, int]:
        if zone_id and zone_id in self._zone_overrides:
            override = self._zone_overrides[zone_id]
            return (
                float(override.get("eps", self._eps)),
                int(override.get("min_samples", self._min_samples)),
            )
        return self._eps, self._min_samples

    def _empty(self, frame: Frame, detection: BirdDetection) -> HuddlingScore:
        return HuddlingScore(
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
