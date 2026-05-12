"""Crowd-density-based huddling detector (CSRNet-style).

Selected via `metadata.json`:
    {"algorithm": "density", "artifact": "model.pt",
     "peak_threshold": 0.6, "peak_min_area_frac": 0.005}

Workflow per frame:
  1. Run a density-estimation CNN (e.g. CSRNet, MCNN, DM-Count) → per-pixel
     bird-density heatmap. Summing the map ≈ total bird count.
  2. Threshold the density map at `peak_threshold × max(map)` → binary peak mask.
  3. Find connected components of high-density regions.
  4. `huddling_score = mass_in_largest_peak / total_mass`

This adapter is included for architectural completeness. There is NO public
chicken-density pre-trained model — to actually use this path, you'd need to:
  1. Convert your existing chicken bounding-box dataset to point-density labels
  2. Train CSRNet (or similar) on it
  3. Save the resulting `.pt` to `models/huddling-detector/<version>/model.pt`
  4. Either match CSRNet's load API directly, OR adapt this loader.

Until then, selecting this version in the dashboard will fail at `start()`
with a clear "model artifact missing" error and the runtime keeps using the
previously-active huddling detector.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import anyio
import numpy as np

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection, HuddlingScore
from edge.inference.model_loader import ModelDescriptor


class DensityHuddlingDetector:
    def __init__(self, descriptor: ModelDescriptor) -> None:
        self._descriptor = descriptor
        meta = descriptor.metadata
        self._peak_threshold = float(meta.get("peak_threshold", 0.6))
        self._peak_min_area_frac = float(meta.get("peak_min_area_frac", 0.005))
        self._input_size = tuple(meta.get("input", {}).get("shape", [1, 3, 384, 384])[2:])
        self._model: Any | None = None
        self._device: str = "cpu"

    @property
    def model_version(self) -> str:
        return self._descriptor.reference

    async def start(self) -> None:
        try:
            import torch  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "Density detector needs PyTorch. Install Jetson torch wheels first."
            ) from exc

        artifact = self._descriptor.artifact_path
        if artifact is None or not artifact.is_file():
            raise FileNotFoundError(
                f"Density model artifact missing: {artifact}. "
                "Train a CSRNet-style density model on chicken density labels and "
                "place model.pt here. There is no public chicken-density pretrain — "
                "see this file's module docstring for training notes."
            )

        device = "cuda" if torch.cuda.is_available() else "cpu"

        def _load() -> Any:
            # torch.load is permissive — accepts state_dict, full module, or
            # TorchScript. We accept whichever produces something with .forward().
            obj = torch.load(str(artifact), map_location=device)
            if hasattr(obj, "eval"):
                obj.eval()
                return obj
            raise RuntimeError(
                "Density model file isn't a loadable module — expected a torch.nn.Module "
                "or scripted graph. Got: " + type(obj).__name__
            )

        self._model = await anyio.to_thread.run_sync(_load)
        self._device = device

    async def score(self, frame: Frame, detection: BirdDetection) -> HuddlingScore:
        if self._model is None:
            await self.start()
        return await anyio.to_thread.run_sync(self._compute, frame, detection)

    # ── private ────────────────────────────────────────────────────────────

    def _compute(self, frame: Frame, detection: BirdDetection) -> HuddlingScore:
        import cv2  # noqa: PLC0415
        import torch  # noqa: PLC0415

        assert self._model is not None

        h_in, w_in = self._input_size
        # Resize + BGR→RGB + normalize to [0,1] + CHW + batch
        img = cv2.resize(frame.image, (int(w_in), int(h_in)))
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        chw = np.ascontiguousarray(rgb.transpose(2, 0, 1), dtype=np.float32) / 255.0
        batch = torch.from_numpy(chw[np.newaxis, ...]).to(self._device)

        with torch.no_grad():
            density = self._model(batch)
        if isinstance(density, (list, tuple)):
            density = density[0]
        d = density.detach().cpu().numpy()
        if d.ndim == 4:
            d = d[0, 0]
        elif d.ndim == 3:
            d = d[0]

        total_mass = float(d.sum())
        if total_mass <= 0:
            return self._empty(frame, detection)

        peak_thresh = self._peak_threshold * float(d.max())
        mask = (d >= peak_thresh).astype(np.uint8)

        # Connected components on the peak mask
        n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        if n_labels <= 1:
            # 0 = background only
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

        min_area = self._peak_min_area_frac * mask.size
        masses: list[float] = []
        for lbl in range(1, n_labels):  # skip background
            area = stats[lbl, cv2.CC_STAT_AREA]
            if area < min_area:
                continue
            masses.append(float(d[labels == lbl].sum()))

        if not masses:
            return self._empty(frame, detection)

        largest_mass = max(masses)
        score = largest_mass / total_mass

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
            cluster_count=len(masses),
            largest_cluster_pct=round(float(score), 4),
        )

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
