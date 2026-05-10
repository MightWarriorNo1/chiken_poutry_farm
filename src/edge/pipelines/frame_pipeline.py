"""Frame pipeline: capture → AI inference → outbox.

Each camera gets its own pipeline instance, run as a child task by main.py.
"""

from __future__ import annotations

import structlog

from edge.capture.source import FrameSource
from edge.domain.events import EventEnvelope, EventType
from edge.inference.inference import BirdDetector, HuddlingDetector, WeightEstimator
from edge.outbox.outbox import Outbox
from edge.telemetry import tracer

log = structlog.get_logger(__name__)
_tracer = tracer("edge.frame_pipeline")


class FramePipeline:
    def __init__(
        self,
        device_id: str,
        source: FrameSource,
        bird_detector: BirdDetector,
        outbox: Outbox,
        weight_estimator: WeightEstimator | None = None,
        huddling_detector: HuddlingDetector | None = None,
        flock_id: str | None = None,
        shed_id: str | None = None,
    ) -> None:
        self._device_id = device_id
        self._source = source
        self._bird = bird_detector
        self._outbox = outbox
        self._weight = weight_estimator
        self._huddling = huddling_detector
        self._flock_id = flock_id
        self._shed_id = shed_id

    async def run(self) -> None:
        await self._source.open()
        try:
            async for frame in self._source.frames():
                with _tracer.start_as_current_span("process_frame") as span:
                    span.set_attribute("camera_id", frame.camera_id)
                    span.set_attribute("frame.sequence", frame.sequence)
                    try:
                        await self._process_one(frame)
                    except Exception as exc:  # noqa: BLE001
                        log.exception("frame.process.failed", error=str(exc))
        finally:
            await self._source.close()

    async def _process_one(self, frame) -> None:  # noqa: ANN001
        detection = await self._bird.detect(frame)
        # Stamp device_id (the detector is device-agnostic by design).
        detection_filled = detection.model_copy(
            update={
                "device_id": self._device_id,
                "shed_id": self._shed_id,
                "flock_id": self._flock_id,
            }
        )
        await self._outbox.put(
            EventEnvelope(
                event_type=EventType.BIRD_DETECTION,
                payload=detection_filled.model_dump(mode="json"),
            )
        )

        if self._weight is not None:
            estimate = await self._weight.estimate(frame, detection_filled)
            await self._outbox.put(
                EventEnvelope(
                    event_type=EventType.WEIGHT_ESTIMATE,
                    payload=estimate.model_copy(
                        update={"device_id": self._device_id}
                    ).model_dump(mode="json"),
                )
            )

        if self._huddling is not None:
            score = await self._huddling.score(frame, detection_filled)
            await self._outbox.put(
                EventEnvelope(
                    event_type=EventType.HUDDLING_SCORE,
                    payload=score.model_copy(
                        update={"device_id": self._device_id}
                    ).model_dump(mode="json"),
                )
            )
