"""TensorRT-backed YOLO bird detector — for Jetson GPU inference.

Same input/output contract as YoloBirdDetector ([bird_detector.py](bird_detector.py))
but uses a pre-compiled `.engine` file via the TensorRT Python bindings + PyCUDA
for GPU memory management. Roughly 3–5× faster than CPU ONNX Runtime on
Orin Nano + FP16 engines.

## Compiling the engine

The engine is **GPU-arch specific** — compile it on the same Jetson the edge
will run on. One-shot:

    trtexec --onnx=models/bird-detector/v1.0.0/model.onnx \
            --saveEngine=models/bird-detector/v1.0.0/model.engine \
            --fp16

Or use [scripts/compile_yolo_trt.py](../../../../scripts/compile_yolo_trt.py).

The detector is auto-selected by [factory.py](../factory.py) whenever a
`model.engine` exists next to the `model.onnx` in the descriptor's version
directory. No config flag needed.

## Pipeline

  1. Letterbox resize → 640×640 with gray (114) padding (same as ONNX path).
  2. BGR→RGB, HWC→CHW, /255, contiguous float32 NCHW.
  3. HtoD memcpy → `execute_async_v3` → DtoH memcpy.
  4. Decode YOLOv8 output `(1, 84, N)` → boxes + class scores.
  5. Confidence + target-class filter → cv2 NMS.
  6. Centroids back to original-image space, normalize to `[0, 1]`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import anyio
import numpy as np

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection
from edge.inference.model_loader import ModelDescriptor

DEFAULT_TARGET_CLASS_ID = 14  # COCO `bird`


class TRTBirdDetector:
    def __init__(self, descriptor: ModelDescriptor, engine_path: Any) -> None:
        self._descriptor = descriptor
        self._engine_path = engine_path
        meta = descriptor.metadata
        input_shape = meta.get("input", {}).get("shape", [1, 3, 640, 640])
        self._input_h = int(input_shape[2])
        self._input_w = int(input_shape[3])
        self._target_classes: set[int] = self._parse_classes(meta.get("classes"))
        thresholds = meta.get("thresholds", {})
        self._conf_threshold = float(thresholds.get("confidence", 0.25))
        self._iou_threshold = float(thresholds.get("iou", 0.45))

        # Populated lazily in start(). Held as Any so this module imports cleanly
        # on machines without tensorrt / pycuda installed.
        self._engine: Any = None
        self._context: Any = None
        self._input_name: str | None = None
        self._output_name: str | None = None
        self._output_shape: tuple[int, ...] | None = None
        self._d_input: Any = None
        self._d_output: Any = None
        self._h_output: np.ndarray | None = None
        self._stream: Any = None

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
        """Deserialize the engine + allocate GPU buffers (slow, blocking)."""
        try:
            import pycuda.autoinit  # noqa: F401, PLC0415  — creates a primary CUDA ctx
            import pycuda.driver as cuda  # noqa: PLC0415
            import tensorrt as trt  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError(
                "TensorRT detector requires `tensorrt` (ships with JetPack) and "
                "`pycuda` (pip install pycuda)."
            ) from exc

        def _load() -> dict[str, Any]:
            logger = trt.Logger(trt.Logger.WARNING)
            with open(self._engine_path, "rb") as f:
                engine_bytes = f.read()
            runtime = trt.Runtime(logger)
            engine = runtime.deserialize_cuda_engine(engine_bytes)
            if engine is None:
                raise RuntimeError(f"Failed to deserialize engine: {self._engine_path}")
            context = engine.create_execution_context()

            # Discover input/output tensor names. TRT 10 deprecates implicit
            # binding indexing; use named tensors.
            input_name: str | None = None
            output_name: str | None = None
            for i in range(engine.num_io_tensors):
                name = engine.get_tensor_name(i)
                if engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT:
                    input_name = name
                else:
                    output_name = name
            if input_name is None or output_name is None:
                raise RuntimeError("Engine missing input or output tensor")

            input_shape = tuple(engine.get_tensor_shape(input_name))
            output_shape = tuple(engine.get_tensor_shape(output_name))

            # Allocate device + pinned host buffers. Float32 (matching the
            # ONNX export); revisit if you compile with --int8 or --fp16-io.
            input_nbytes = int(np.prod(input_shape) * 4)
            output_nbytes = int(np.prod(output_shape) * 4)
            d_input = cuda.mem_alloc(input_nbytes)
            d_output = cuda.mem_alloc(output_nbytes)
            h_output = np.empty(output_shape, dtype=np.float32)

            context.set_tensor_address(input_name, int(d_input))
            context.set_tensor_address(output_name, int(d_output))

            return {
                "engine": engine,
                "context": context,
                "input_name": input_name,
                "output_name": output_name,
                "output_shape": output_shape,
                "d_input": d_input,
                "d_output": d_output,
                "h_output": h_output,
                "stream": cuda.Stream(),
            }

        state = await anyio.to_thread.run_sync(_load)
        self._engine = state["engine"]
        self._context = state["context"]
        self._input_name = state["input_name"]
        self._output_name = state["output_name"]
        self._output_shape = state["output_shape"]
        self._d_input = state["d_input"]
        self._d_output = state["d_output"]
        self._h_output = state["h_output"]
        self._stream = state["stream"]

    async def detect(self, frame: Frame) -> BirdDetection:
        if self._context is None:
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
        import pycuda.driver as cuda  # noqa: PLC0415

        assert (
            self._context is not None
            and self._d_input is not None
            and self._d_output is not None
            and self._h_output is not None
            and self._stream is not None
        )

        # 1. Letterbox (preserves aspect, gray pad).
        scale = min(self._input_w / orig_w, self._input_h / orig_h)
        new_w = int(round(orig_w * scale))
        new_h = int(round(orig_h * scale))
        pad_x = (self._input_w - new_w) // 2
        pad_y = (self._input_h - new_h) // 2

        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((self._input_h, self._input_w, 3), 114, dtype=np.uint8)
        canvas[pad_y : pad_y + new_h, pad_x : pad_x + new_w] = resized

        # 2. BGR→RGB, HWC→CHW, normalize, batch dim, contiguous float32.
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        chw = np.ascontiguousarray(rgb.transpose(2, 0, 1), dtype=np.float32) / 255.0
        batch = np.ascontiguousarray(chw[np.newaxis, :, :, :])

        # 3. HtoD → execute → DtoH on a single CUDA stream.
        cuda.memcpy_htod_async(self._d_input, batch, self._stream)
        self._context.execute_async_v3(stream_handle=self._stream.handle)
        cuda.memcpy_dtoh_async(self._h_output, self._d_output, self._stream)
        self._stream.synchronize()

        out = self._h_output
        if out.ndim == 3:
            out = out[0]
        # YOLOv8 ONNX layout is (84, N); transpose if needed.
        if out.shape[0] < out.shape[1]:
            out = out.T

        boxes = out[:, :4]
        scores_all = out[:, 4:]

        # 4. Filter by max class score + target classes.
        class_ids = np.argmax(scores_all, axis=1)
        max_scores = np.max(scores_all, axis=1)
        keep = max_scores >= self._conf_threshold
        if self._target_classes:
            keep &= np.isin(class_ids, list(self._target_classes))

        boxes = boxes[keep]
        scores = max_scores[keep]
        if len(boxes) == 0:
            return 0, 0.0, []

        # 5. NMS via cv2 (xywh in pixel space).
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
        if w <= 0 or h <= 0:
            return 0.0
        per_mp = bird_count / ((w * h) / 1_000_000)
        return float(min(1.0, per_mp / 50.0))
