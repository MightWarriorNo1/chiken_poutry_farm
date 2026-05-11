"""YOLO bird detector backed by ONNX Runtime.

Pipeline:
  1. Letterbox resize input frame to model's expected input (default 640×640),
     preserving aspect ratio with gray (114) padding.
  2. BGR→RGB, HWC→CHW, normalize to [0, 1], add batch dim.
  3. Run ONNX session (CUDA EP if available, else CPU).
  4. Decode YOLOv8 output (1, 84, N) → boxes (xywh, 640-space) + class scores.
  5. Filter to target classes (default: COCO `bird` = 14) above confidence threshold.
  6. NMS via cv2.dnn.NMSBoxes.
  7. Convert centroids back to original image space, normalize to [0, 1], clamp.

Production swap: the same `model.onnx` runs unchanged on TensorRT (Jetson) by
adding `TensorrtExecutionProvider` to the EP preference list.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import anyio
import numpy as np

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection
from edge.inference.model_loader import ModelDescriptor

# Default if metadata doesn't override — matches Ultralytics' COCO export.
DEFAULT_TARGET_CLASS_ID = 14  # 'bird'


class YoloBirdDetector:
    def __init__(self, descriptor: ModelDescriptor) -> None:
        self._descriptor = descriptor
        meta = descriptor.metadata
        input_shape = meta.get("input", {}).get("shape", [1, 3, 640, 640])
        # Expect (N, C, H, W).
        self._input_h = int(input_shape[2])
        self._input_w = int(input_shape[3])
        self._target_classes: set[int] = self._parse_classes(meta.get("classes"))
        thresholds = meta.get("thresholds", {})
        self._conf_threshold = float(thresholds.get("confidence", 0.25))
        self._iou_threshold = float(thresholds.get("iou", 0.45))
        self._session: Any | None = None
        self._input_name: str | None = None

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
        """Lazy: open the ONNX session in a worker thread (it's slow)."""
        try:
            import onnxruntime as ort  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "Install the `ai` extra: pip install -e '.[ai]'"
            ) from exc

        artifact = self._descriptor.artifact_path
        if artifact is None or not artifact.is_file():
            raise FileNotFoundError(f"Model artifact not found: {artifact}")

        def _create() -> Any:
            providers = self._available_providers(ort)
            sess_opts = ort.SessionOptions()
            # Reasonable defaults for an edge box; can be tuned per device.
            sess_opts.intra_op_num_threads = max(1, _cpu_count() // 2)
            sess_opts.inter_op_num_threads = 1
            return ort.InferenceSession(str(artifact), sess_opts, providers=providers)

        self._session = await anyio.to_thread.run_sync(_create)
        self._input_name = self._session.get_inputs()[0].name

    @staticmethod
    def _available_providers(ort: Any) -> list[str]:
        # Order of preference: TensorRT > CUDA > CPU.
        preferred = [
            "TensorrtExecutionProvider",
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ]
        avail = set(ort.get_available_providers())
        return [p for p in preferred if p in avail] or ["CPUExecutionProvider"]

    async def detect(self, frame: Frame) -> BirdDetection:
        if self._session is None:
            await self.start()

        bird_count, mean_conf, centroids = await anyio.to_thread.run_sync(
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
        )

    # ── private inference plumbing ─────────────────────────────────────────
    def _infer(
        self,
        image: np.ndarray,
        orig_w: int,
        orig_h: int,
    ) -> tuple[int, float, list[tuple[float, float]]]:
        import cv2  # noqa: PLC0415

        assert self._session is not None and self._input_name is not None

        # 1. Letterbox.
        scale = min(self._input_w / orig_w, self._input_h / orig_h)
        new_w = int(round(orig_w * scale))
        new_h = int(round(orig_h * scale))
        pad_x = (self._input_w - new_w) // 2
        pad_y = (self._input_h - new_h) // 2

        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((self._input_h, self._input_w, 3), 114, dtype=np.uint8)
        canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized

        # 2. BGR→RGB, HWC→CHW, normalize, add batch dim.
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        chw = np.ascontiguousarray(rgb.transpose(2, 0, 1), dtype=np.float32) / 255.0
        batch = chw[np.newaxis, :, :, :]

        # 3. Run inference.
        outputs = self._session.run(None, {self._input_name: batch})
        out = outputs[0]
        if out.ndim == 3:
            out = out[0]  # (84, N)

        # YOLOv8 ONNX layout is (84, N) — transpose to (N, 84).
        if out.shape[0] < out.shape[1]:
            out = out.T

        boxes = out[:, :4]
        scores_all = out[:, 4:]

        # 4. Filter by max class score.
        class_ids = np.argmax(scores_all, axis=1)
        max_scores = np.max(scores_all, axis=1)
        keep = max_scores >= self._conf_threshold
        if self._target_classes:
            keep &= np.isin(class_ids, list(self._target_classes))

        boxes = boxes[keep]
        scores = max_scores[keep]
        if len(boxes) == 0:
            return 0, 0.0, []

        # 5. NMS — cv2 wants (x, y, w, h) in pixel space + python lists.
        xc, yc, bw, bh = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        nms_boxes = np.stack([xc - bw / 2, yc - bh / 2, bw, bh], axis=1).tolist()
        keep_idx = cv2.dnn.NMSBoxes(
            nms_boxes,
            scores.tolist(),
            self._conf_threshold,
            self._iou_threshold,
        )
        if len(keep_idx) == 0:
            return 0, 0.0, []
        keep_idx = np.asarray(keep_idx).flatten()
        boxes = boxes[keep_idx]
        scores = scores[keep_idx]

        # 6. Centroids back to original image, normalized + clamped.
        centroids: list[tuple[float, float]] = []
        for cx_640, cy_640 in zip(boxes[:, 0].tolist(), boxes[:, 1].tolist(), strict=True):
            cx_orig = (cx_640 - pad_x) / scale
            cy_orig = (cy_640 - pad_y) / scale
            centroids.append(
                (
                    float(np.clip(cx_orig / orig_w, 0.0, 1.0)),
                    float(np.clip(cy_orig / orig_h, 0.0, 1.0)),
                )
            )

        return len(centroids), float(np.mean(scores)), centroids

    @staticmethod
    def _density_score(bird_count: int, w: int, h: int) -> float:
        # Birds-per-megapixel, soft-saturating at 50 birds/MP.
        if w <= 0 or h <= 0:
            return 0.0
        per_mp = bird_count / ((w * h) / 1_000_000)
        return float(min(1.0, per_mp / 50.0))


def _cpu_count() -> int:
    import os  # noqa: PLC0415

    return os.cpu_count() or 1
