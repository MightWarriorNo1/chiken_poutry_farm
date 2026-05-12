"""YOLOv8-seg based huddling detector.

Selected via `metadata.json`:
    {"algorithm": "yolo-seg", "artifact": "model.pt",
     "dilate_px": 30, "thresholds": {"confidence": 0.25, "iou": 0.45}}

Workflow per frame:
  1. Run a YOLOv8 segmentation model → per-chicken pixel masks
  2. Dilate each mask by `dilate_px` (so chickens "almost touching" count as
     adjacent — accounts for the typical few-pixel gap between segmentations
     of adjacent chickens)
  3. Two chickens are adjacent ⇔ their dilated masks overlap
  4. Find connected components in the adjacency graph
  5. `huddling_score = largest_component_size / total_chickens`

Strictly better than centroid-DBSCAN when chickens overlap or partially
occlude each other, because masks capture body shape, not just a point.

Requires a `.pt` trained with `task=segment`. The default `bird-detector`
model from drcardinal/chicken-detector is `task=detect` (boxes only) and
will NOT work here — you'd need to train a separate seg model on polygon-
labeled chicken data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import anyio
import numpy as np

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection, HuddlingScore
from edge.inference.model_loader import ModelDescriptor


class SegHuddlingDetector:
    def __init__(self, descriptor: ModelDescriptor) -> None:
        self._descriptor = descriptor
        meta = descriptor.metadata
        self._dilate_px = int(meta.get("dilate_px", 30))
        thresholds = meta.get("thresholds", {})
        self._conf = float(thresholds.get("confidence", 0.25))
        self._iou = float(thresholds.get("iou", 0.45))
        self._model: Any | None = None
        self._device: str | int = "cpu"

    @property
    def model_version(self) -> str:
        return self._descriptor.reference

    async def start(self) -> None:
        try:
            from ultralytics import YOLO  # noqa: PLC0415
            import torch  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "Install ultralytics + Jetson PyTorch (see requirements-jetson.txt)."
            ) from exc

        artifact = self._descriptor.artifact_path
        if artifact is None or not artifact.is_file():
            raise FileNotFoundError(
                f"YOLOv8-seg model artifact missing: {artifact}. "
                "Train a segmentation model on chicken polygons and place model.pt here."
            )

        device: str | int = 0 if torch.cuda.is_available() else "cpu"

        def _load() -> Any:
            m = YOLO(str(artifact))
            try:
                m.to(device)
            except Exception:  # noqa: BLE001
                pass
            return m

        self._model = await anyio.to_thread.run_sync(_load)
        self._device = device

    async def score(self, frame: Frame, detection: BirdDetection) -> HuddlingScore:
        if self._model is None:
            await self.start()
        return await anyio.to_thread.run_sync(self._compute, frame, detection)

    # ── private ────────────────────────────────────────────────────────────

    def _compute(self, frame: Frame, detection: BirdDetection) -> HuddlingScore:
        import cv2  # noqa: PLC0415

        assert self._model is not None

        results = self._model.predict(
            frame.image,
            conf=self._conf,
            iou=self._iou,
            device=self._device,
            verbose=False,
        )
        if not results:
            return self._empty(frame, detection)

        r = results[0]
        masks = getattr(r, "masks", None)
        if masks is None or masks.data is None or len(masks.data) == 0:
            return self._empty(frame, detection)

        # masks.data is (N, h, w) in [0,1] — convert to uint8 binary
        try:
            arr = masks.data.cpu().numpy()
        except AttributeError:
            arr = np.asarray(masks.data, dtype=np.float32)
        bin_masks = (arr > 0.5).astype(np.uint8)
        n = bin_masks.shape[0]
        if n == 0:
            return self._empty(frame, detection)

        # Dilate each mask so "almost touching" counts.
        k = max(1, self._dilate_px)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))
        dilated = np.stack([cv2.dilate(m, kernel) for m in bin_masks], axis=0)

        # Adjacency: O(N²) — fine up to ~200 chickens; bigger flocks need a
        # spatial-hash optimization (out of scope for v1).
        adj: list[list[int]] = [[] for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                if np.any(dilated[i] & dilated[j]):
                    adj[i].append(j)
                    adj[j].append(i)

        components = self._connected_components(n, adj)
        if not components:
            return self._empty(frame, detection)

        largest = max(len(c) for c in components)
        score = largest / n

        return HuddlingScore(
            device_id="",
            camera_id=frame.camera_id,
            shed_id=detection.shed_id,
            flock_id=detection.flock_id,
            zone_id=detection.zone_id,
            captured_at=frame.captured_at,
            processed_at=datetime.now(timezone.utc),
            model_version=self.model_version,
            huddling_score=round(float(score), 4),
            cluster_count=len(components),
            largest_cluster_pct=round(float(score), 4),
        )

    @staticmethod
    def _connected_components(n: int, adj: list[list[int]]) -> list[list[int]]:
        seen = [False] * n
        out: list[list[int]] = []
        for start in range(n):
            if seen[start]:
                continue
            stack = [start]
            comp: list[int] = []
            while stack:
                v = stack.pop()
                if seen[v]:
                    continue
                seen[v] = True
                comp.append(v)
                stack.extend(adj[v])
            out.append(comp)
        return out

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
