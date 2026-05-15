"""YOLO bird detector backed by the `ultralytics` Python API.

Used when the model artifact is a `.pt` (PyTorch state dict) — typically a
pretrained or fine-tuned YOLOv8/YOLO11 checkpoint. On Jetson with the
NVIDIA-built PyTorch wheel installed, `ultralytics` runs inference on the
integrated GPU via `torch.cuda` automatically.

Sister adapter to `bird_detector.YoloBirdDetector` (which targets `.onnx`
artifacts via ONNX Runtime). Same input/output contract — the factory picks
which one to instantiate based on `descriptor.artifact_path.suffix`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import anyio
import numpy as np

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection
from edge.inference.model_loader import ModelDescriptor

DEFAULT_TARGET_CLASS_ID = 14  # COCO 'bird'


class UltralyticsBirdDetector:
    """Wraps `ultralytics.YOLO(...)` so it satisfies the BirdDetector port."""

    def __init__(self, descriptor: ModelDescriptor) -> None:
        self._descriptor = descriptor
        meta = descriptor.metadata
        self._target_classes: list[int] = sorted(self._parse_classes(meta.get("classes")))
        thresholds = meta.get("thresholds", {})
        self._conf_threshold = float(thresholds.get("confidence", 0.25))
        self._iou_threshold = float(thresholds.get("iou", 0.45))
        # ultralytics defaults to 640; metadata may override.
        input_shape = meta.get("input", {}).get("shape", [1, 3, 640, 640])
        self._imgsz = int(input_shape[2]) if len(input_shape) >= 3 else 640
        self._model: Any | None = None
        self._device: str | int = "cpu"

    @property
    def model_version(self) -> str:
        return self._descriptor.reference

    @staticmethod
    def _parse_classes(raw: Any) -> set[int]:
        if not raw:
            return {DEFAULT_TARGET_CLASS_ID}
        out: set[int] = set()
        for c in raw:
            if isinstance(c, dict) and "id" in c:
                out.add(int(c["id"]))
            elif isinstance(c, (int, str)):
                try:
                    out.add(int(c))
                except (TypeError, ValueError):
                    continue
        return out or {DEFAULT_TARGET_CLASS_ID}

    async def start(self) -> None:
        """Lazy-load the model on a worker thread (PyTorch import + .pt load is slow)."""
        try:
            from ultralytics import YOLO  # noqa: PLC0415
            import torch  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "Install ultralytics + Jetson PyTorch (see requirements-jetson.txt)."
            ) from exc

        artifact = self._descriptor.artifact_path
        if artifact is None or not artifact.is_file():
            raise FileNotFoundError(f"Model artifact not found: {artifact}")

        device: str | int
        if torch.cuda.is_available():
            device = 0
        else:
            device = "cpu"

        def _load() -> Any:
            model = YOLO(str(artifact))
            # Touch one tiny tensor on the chosen device so the first real predict()
            # doesn't pay the CUDA init cost mid-pipeline.
            try:
                model.to(device)
            except Exception:  # noqa: BLE001
                pass
            return model

        self._model = await anyio.to_thread.run_sync(_load)
        self._device = device

    async def detect(self, frame: Frame) -> BirdDetection:
        if self._model is None:
            await self.start()

        bird_count, mean_conf, centroids, bboxes = await anyio.to_thread.run_sync(
            self._infer, frame.image, frame.width, frame.height
        )

        return BirdDetection(
            device_id="",  # filled in by the pipeline
            camera_id=frame.camera_id,
            captured_at=frame.captured_at,
            processed_at=datetime.now(timezone.utc),
            model_version=self.model_version,
            bird_count=bird_count,
            density_score=self._density_score(bird_count, frame.width, frame.height),
            confidence=mean_conf,
            bbox_centroids=centroids,
            bboxes=bboxes,
        )

    # ── private inference plumbing ─────────────────────────────────────────
    def _infer(
        self,
        image: np.ndarray,
        orig_w: int,
        orig_h: int,
    ) -> tuple[
        int,
        float,
        list[tuple[float, float]],
        list[tuple[float, float, float, float]],
    ]:
        assert self._model is not None

        results = self._model.predict(
            image,
            imgsz=self._imgsz,
            conf=self._conf_threshold,
            iou=self._iou_threshold,
            classes=self._target_classes,
            device=self._device,
            verbose=False,
        )
        if not results:
            return 0, 0.0, []

        # ultralytics returns one Result per input; we always pass a single frame.
        r = results[0]
        if r.boxes is None or len(r.boxes) == 0:
            return 0, 0.0, []

        # boxes.xywh is (N, 4) in *original-image* pixel coords (ultralytics
        # un-letterboxes for us). conf is (N,).
        try:
            xywh = r.boxes.xywh.cpu().numpy()
            conf = r.boxes.conf.cpu().numpy()
        except AttributeError:
            # Fallback if Tensor accessors differ across versions.
            xywh = np.asarray(r.boxes.xywh, dtype=np.float32)
            conf = np.asarray(r.boxes.conf, dtype=np.float32)

        if xywh.size == 0:
            return 0, 0.0, [], []

        # Normalize + clamp to [0, 1] for the BirdDetection schema.
        w_norm = max(orig_w, 1)
        h_norm = max(orig_h, 1)
        centroids: list[tuple[float, float]] = []
        bboxes: list[tuple[float, float, float, float]] = []
        for cx_p, cy_p, bw_p, bh_p in xywh.tolist():
            cx = float(np.clip(cx_p / w_norm, 0.0, 1.0))
            cy = float(np.clip(cy_p / h_norm, 0.0, 1.0))
            bw = float(np.clip(bw_p / w_norm, 0.0, 1.0))
            bh = float(np.clip(bh_p / h_norm, 0.0, 1.0))
            centroids.append((cx, cy))
            bboxes.append((cx, cy, bw, bh))
        return len(centroids), float(np.mean(conf)), centroids, bboxes

    @staticmethod
    def _density_score(bird_count: int, w: int, h: int) -> float:
        if w <= 0 or h <= 0:
            return 0.0
        per_mp = bird_count / ((w * h) / 1_000_000)
        return float(min(1.0, per_mp / 50.0))
