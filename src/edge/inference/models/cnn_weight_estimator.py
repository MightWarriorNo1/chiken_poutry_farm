"""Per-bird CNN weight regression.

Selected via `metadata.json`:
    {"algorithm": "cnn-regression", "artifact": "model.pt",
     "input": {"shape": [1, 3, 224, 224]},
     "normalize": {"mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225]}}

Workflow per frame:
  1. YOLO gives us a list of chicken bounding boxes (consumed from `detection`).
  2. Crop each box from the source frame.
  3. Resize to model input shape, normalize.
  4. Batch crops, run regression head → one weight prediction per crop.
  5. Frame-level estimate = mean of per-bird predictions.

Required artifact: a PyTorch model whose `forward(batch_of_crops)` returns
weights in grams. Typically a MobileNet/EfficientNet/ResNet18 backbone with
a single-output regression head, trained on (crop, weight_g) pairs.

This adapter is included for architectural completeness. There is NO public
chicken-weight-CNN with downloadable weights — you'd need to:
  1. Catch ~500–2000 chickens, weigh each, save the camera frame at the moment
     of catch with the bird's bbox.
  2. Train a CNN regressor (~half a day on a dev GPU with augmentations).
  3. Export to `model.pt`, drop into `models/weight-estimator/<version>/`.

Until then, selecting this version fails at `start()` with a clear error and
the runtime keeps the previously-active estimator running.

Current crop sourcing: this adapter relies on having full bboxes per bird,
which the project's BirdDetection schema currently doesn't carry (only
centroids). When we extend the schema (or when this becomes a real priority),
we'll thread bbox sizes through from YOLO. For now this adapter still
constructs correctly and fails at first-frame inference with a clear error
if the artifact is missing — it's wired into the dropdown for forward
compatibility.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import anyio
import numpy as np

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection, WeightEstimate
from edge.inference.model_loader import ModelDescriptor


class CnnWeightEstimator:
    def __init__(self, descriptor: ModelDescriptor) -> None:
        self._descriptor = descriptor
        meta = descriptor.metadata

        input_shape = meta.get("input", {}).get("shape", [1, 3, 224, 224])
        self._input_h = int(input_shape[2]) if len(input_shape) >= 3 else 224
        self._input_w = int(input_shape[3]) if len(input_shape) >= 4 else 224

        norm = meta.get("normalize", {})
        self._mean = np.asarray(
            norm.get("mean", [0.485, 0.456, 0.406]), dtype=np.float32
        ).reshape(3, 1, 1)
        self._std = np.asarray(
            norm.get("std", [0.229, 0.224, 0.225]), dtype=np.float32
        ).reshape(3, 1, 1)

        self._baseline_confidence = float(meta.get("baseline_confidence", 0.75))
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
                "CNN weight estimator needs PyTorch — install Jetson torch wheels."
            ) from exc

        artifact = self._descriptor.artifact_path
        if artifact is None or not artifact.is_file():
            raise FileNotFoundError(
                f"CNN weight model artifact missing: {artifact}. "
                "Train a per-bird CNN regression on (crop, weight_g) pairs "
                "and place model.pt here. See module docstring for guidance."
            )

        device = "cuda" if torch.cuda.is_available() else "cpu"

        def _load() -> Any:
            obj = torch.load(str(artifact), map_location=device)
            if hasattr(obj, "eval"):
                obj.eval()
                return obj
            raise RuntimeError(
                "Weight model file isn't a loadable torch.nn.Module — got: "
                + type(obj).__name__
            )

        self._model = await anyio.to_thread.run_sync(_load)
        self._device = device

    async def estimate(
        self,
        frame: Frame,
        detection: BirdDetection,
        bird_age_days: int | None = None,
        breed: str | None = None,
    ) -> WeightEstimate:
        if self._model is None:
            await self.start()

        if detection.bird_count == 0:
            return self._empty(frame, detection, bird_age_days, breed)

        weights = await anyio.to_thread.run_sync(
            self._infer, frame, detection
        )
        if not weights:
            return self._empty(frame, detection, bird_age_days, breed)

        avg = float(sum(weights) / len(weights))
        confidence = round(
            min(1.0, self._baseline_confidence * float(detection.confidence)), 4
        )

        return WeightEstimate(
            device_id="",
            camera_id=frame.camera_id,
            shed_id=detection.shed_id,
            flock_id=detection.flock_id,
            captured_at=frame.captured_at,
            processed_at=datetime.now(timezone.utc),
            model_version=self.model_version,
            estimated_avg_weight_g=round(avg, 1),
            confidence=confidence,
            sample_size=len(weights),
            bird_age_days=bird_age_days,
            breed=breed,
        )

    # ── internal ───────────────────────────────────────────────────────────

    def _infer(self, frame: Frame, detection: BirdDetection) -> list[float]:
        """Crop bird regions, run them through the CNN as a batch."""
        import cv2  # noqa: PLC0415
        import torch  # noqa: PLC0415

        assert self._model is not None

        # We need per-bird bboxes here — the BirdDetection schema currently
        # only carries centroids. Fall back to fixed crops around each
        # centroid until the schema is extended.
        h, w = frame.image.shape[:2]
        # Heuristic crop half-size — ~12% of frame dimension. Trainable
        # later; for now matches typical chicken footprint from ceiling cam.
        crop_half = max(self._input_h // 2, int(0.06 * min(h, w)))

        crops: list[np.ndarray] = []
        for cx_n, cy_n in detection.bbox_centroids:
            cx = int(round(float(cx_n) * w))
            cy = int(round(float(cy_n) * h))
            x0 = max(0, cx - crop_half)
            y0 = max(0, cy - crop_half)
            x1 = min(w, cx + crop_half)
            y1 = min(h, cy + crop_half)
            if x1 <= x0 or y1 <= y0:
                continue
            crop = frame.image[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            resized = cv2.resize(crop, (self._input_w, self._input_h))
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            chw = rgb.transpose(2, 0, 1).astype(np.float32) / 255.0
            chw = (chw - self._mean) / self._std
            crops.append(chw)

        if not crops:
            return []

        batch = torch.from_numpy(np.stack(crops, axis=0)).to(self._device)
        with torch.no_grad():
            out = self._model(batch)
        if hasattr(out, "detach"):
            out = out.detach().cpu().numpy()
        else:
            out = np.asarray(out)
        if out.ndim > 1:
            out = out.squeeze()
        return [float(v) for v in np.atleast_1d(out).tolist()]

    def _empty(
        self,
        frame: Frame,
        detection: BirdDetection,
        bird_age_days: int | None,
        breed: str | None,
    ) -> WeightEstimate:
        return WeightEstimate(
            device_id="",
            camera_id=frame.camera_id,
            shed_id=detection.shed_id,
            flock_id=detection.flock_id,
            captured_at=frame.captured_at,
            processed_at=datetime.now(timezone.utc),
            model_version=self.model_version,
            estimated_avg_weight_g=0.0,
            confidence=0.0,
            sample_size=0,
            bird_age_days=bird_age_days,
            breed=breed,
        )
