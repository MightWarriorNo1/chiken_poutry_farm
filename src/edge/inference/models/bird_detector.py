"""YOLOv8 bird detector — ONNX Runtime adapter.

Pipeline:
  letterbox → CHW float32 → onnxruntime → filter bird class → NMS → centroids

Designed to run unchanged on:
  - amd64 dev laptops (CPUExecutionProvider)
  - NVIDIA Jetson (CUDAExecutionProvider, TensorRTExecutionProvider via onnxruntime-gpu)
Provider selection is automatic based on `onnxruntime.get_available_providers()`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import anyio
import numpy as np
import structlog

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection
from edge.inference.model_loader import ModelDescriptor

log = structlog.get_logger(__name__)

# COCO class id for bird. YOLOv8n pretrained outputs COCO classes; we use this as a
# poultry proxy until a fine-tuned poultry model lands (Sprint 4 roadmap).
_DEFAULT_BIRD_CLASS_ID = 14
_DEFAULT_INPUT_SIZE = 640
_PROVIDER_PRIORITY = (
    "TensorrtExecutionProvider",  # Jetson with TRT
    "CUDAExecutionProvider",       # any CUDA host
    "CPUExecutionProvider",        # always available
)


class YoloBirdDetector:
    """Bird detector backed by an ONNX Runtime session.

    Stateless w.r.t. frames; safe to share across cameras. `start()` is idempotent
    and protected by an async lock so concurrent first-frame arrivals don't race
    on session creation.
    """

    def __init__(
        self,
        descriptor: ModelDescriptor,
        confidence_threshold: float | None = None,
        iou_threshold: float | None = None,
    ) -> None:
        self._descriptor = descriptor
        meta = descriptor.metadata

        thresholds: dict[str, Any] = meta.get("thresholds", {}) if isinstance(meta, dict) else {}
        self._conf_thresh = float(confidence_threshold or thresholds.get("confidence", 0.25))
        self._iou_thresh = float(iou_threshold or thresholds.get("iou", 0.45))

        input_meta: dict[str, Any] = meta.get("input", {}) if isinstance(meta, dict) else {}
        input_shape = input_meta.get("shape", [1, 3, _DEFAULT_INPUT_SIZE, _DEFAULT_INPUT_SIZE])
        self._input_size = int(input_shape[-1])

        class_map = meta.get("class_id_map", {}) if isinstance(meta, dict) else {}
        self._bird_class_id = int(class_map.get("bird", _DEFAULT_BIRD_CLASS_ID))

        self._session: Any = None
        self._input_name: str | None = None
        self._start_lock = anyio.Lock()

    @property
    def model_version(self) -> str:
        return self._descriptor.reference

    async def start(self) -> None:
        async with self._start_lock:
            if self._session is not None:
                return
            try:
                import onnxruntime as ort  # noqa: PLC0415
            except ImportError as exc:
                raise RuntimeError("Install with: pip install -e '.[ai]'") from exc

            def _create() -> Any:
                available = set(ort.get_available_providers())
                providers = [p for p in _PROVIDER_PRIORITY if p in available]
                return ort.InferenceSession(
                    str(self._descriptor.artifact_path),
                    providers=providers,
                )

            self._session = await anyio.to_thread.run_sync(_create)
            self._input_name = self._session.get_inputs()[0].name
            log.info(
                "yolo.session.ready",
                model=self.model_version,
                providers=self._session.get_providers(),
                input_name=self._input_name,
                input_size=self._input_size,
            )

    async def detect(self, frame: Frame) -> BirdDetection:
        if self._session is None:
            await self.start()
        count, mean_conf, centroids = await anyio.to_thread.run_sync(
            self._run_inference, frame.image, frame.width, frame.height
        )
        return BirdDetection(
            device_id="",  # filled in by the pipeline
            camera_id=frame.camera_id,
            captured_at=frame.captured_at,
            processed_at=datetime.now(timezone.utc),
            model_version=self.model_version,
            bird_count=count,
            density_score=self._density_score(count, frame.width, frame.height),
            confidence=mean_conf,
            bbox_centroids=centroids,
        )

    # ── private ────────────────────────────────────────────────────────────
    def _run_inference(
        self,
        image: np.ndarray,
        orig_width: int,
        orig_height: int,
    ) -> tuple[int, float, list[tuple[float, float]]]:
        tensor, scale, pad = self._letterbox(image)
        outputs = self._session.run(None, {self._input_name: tensor})
        return self._postprocess(outputs[0], scale, pad, orig_width, orig_height)

    def _letterbox(
        self, image: np.ndarray
    ) -> tuple[np.ndarray, float, tuple[int, int]]:
        """Resize preserving aspect ratio + pad to square. YOLO-standard."""
        import cv2  # noqa: PLC0415

        h, w = image.shape[:2]
        target = self._input_size
        scale = min(target / w, target / h)
        new_w, new_h = int(round(w * scale)), int(round(h * scale))
        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        pad_w = (target - new_w) // 2
        pad_h = (target - new_h) // 2
        padded = np.full((target, target, 3), 114, dtype=np.uint8)
        padded[pad_h : pad_h + new_h, pad_w : pad_w + new_w] = resized

        # BGR → RGB, HWC → CHW, [0, 255] → [0, 1], add batch dim
        tensor = padded[..., ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
        return np.expand_dims(tensor, axis=0), scale, (pad_w, pad_h)

    def _postprocess(
        self,
        raw: np.ndarray,
        scale: float,
        pad: tuple[int, int],
        orig_w: int,
        orig_h: int,
    ) -> tuple[int, float, list[tuple[float, float]]]:
        """raw: [1, 4+num_classes, anchors]. Returns (count, mean_conf, norm_centroids)."""
        import cv2  # noqa: PLC0415

        # Standard YOLOv8 ONNX output is [4+C, N] (C≈80, N≈8400). Normalize to [N, 4+C].
        preds = raw[0]
        if preds.shape[0] < preds.shape[1]:
            preds = preds.T  # [4+C, N] → [N, 4+C]

        class_col = 4 + self._bird_class_id
        if class_col >= preds.shape[1]:
            return 0, 0.0, []

        scores = preds[:, class_col]
        mask = scores > self._conf_thresh
        if not mask.any():
            return 0, 0.0, []

        kept = preds[mask]
        kept_scores = scores[mask]

        # xywh in letterbox-pixel space → original pixel space.
        pad_w, pad_h = pad
        cx = (kept[:, 0] - pad_w) / scale
        cy = (kept[:, 1] - pad_h) / scale
        w_ = kept[:, 2] / scale
        h_ = kept[:, 3] / scale

        # cv2 NMS expects [x, y, w, h] in pixel space.
        boxes = np.stack([cx - w_ / 2, cy - h_ / 2, w_, h_], axis=1).tolist()
        keep = cv2.dnn.NMSBoxes(
            bboxes=boxes,
            scores=kept_scores.tolist(),
            score_threshold=self._conf_thresh,
            nms_threshold=self._iou_thresh,
        )
        # cv2 returns ndarray or sequence depending on version — normalize.
        if isinstance(keep, np.ndarray):
            indices = keep.flatten().tolist()
        else:
            indices = [int(i) for i in (keep or [])]

        if not indices:
            return 0, 0.0, []

        centroids: list[tuple[float, float]] = []
        for i in indices:
            nx = float(np.clip(cx[i] / orig_w, 0.0, 1.0))
            ny = float(np.clip(cy[i] / orig_h, 0.0, 1.0))
            centroids.append((nx, ny))

        mean_conf = float(np.mean(kept_scores[indices]))
        return len(indices), mean_conf, centroids

    @staticmethod
    def _density_score(bird_count: int, w: int, h: int) -> float:
        """Birds per megapixel, saturating at 50 birds/MP. Tunable later."""
        if w <= 0 or h <= 0:
            return 0.0
        per_mp = bird_count / ((w * h) / 1_000_000)
        return float(min(1.0, per_mp / 50.0))
