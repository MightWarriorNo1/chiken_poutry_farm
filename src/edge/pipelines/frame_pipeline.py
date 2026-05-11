"""Frame pipeline: capture → AI inference → outbox (+ optional live stream).

Each camera gets its own pipeline instance, run as a child task by main.py.

If a FrameBroadcaster is wired in, the pipeline annotates each post-inference
frame (centroid dots + HUD) and publishes the JPEG to the dashboard's MJPEG
stream. Annotation + JPEG encode only run when at least one subscriber is
connected — no overhead when nobody's watching.
"""

from __future__ import annotations

from functools import partial

import anyio
import structlog

from edge.capture.source import Frame, FrameSource
from edge.dashboard.frame_broadcaster import FrameBroadcaster
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
        flock_age_days: int | None = None,
        breed: str | None = None,
        broadcaster: FrameBroadcaster | None = None,
    ) -> None:
        self._device_id = device_id
        self._source = source
        self._bird = bird_detector
        self._outbox = outbox
        self._weight = weight_estimator
        self._huddling = huddling_detector
        self._flock_id = flock_id
        self._shed_id = shed_id
        self._flock_age_days = flock_age_days
        self._breed = breed
        self._broadcaster = broadcaster

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

    async def _process_one(self, frame: Frame) -> None:
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

        weight_g: float | None = None
        if self._weight is not None:
            estimate = await self._weight.estimate(
                frame,
                detection_filled,
                bird_age_days=self._flock_age_days,
                breed=self._breed,
            )
            weight_g = float(estimate.estimated_avg_weight_g)
            await self._outbox.put(
                EventEnvelope(
                    event_type=EventType.WEIGHT_ESTIMATE,
                    payload=estimate.model_copy(
                        update={"device_id": self._device_id}
                    ).model_dump(mode="json"),
                )
            )

        huddling_score: float | None = None
        if self._huddling is not None:
            score = await self._huddling.score(frame, detection_filled)
            huddling_score = float(score.huddling_score)
            await self._outbox.put(
                EventEnvelope(
                    event_type=EventType.HUDDLING_SCORE,
                    payload=score.model_copy(
                        update={"device_id": self._device_id}
                    ).model_dump(mode="json"),
                )
            )

        # Live dashboard stream — skip entirely when nobody's watching so we
        # don't pay annotation + JPEG-encode cost on every frame.
        if self._broadcaster is not None and self._broadcaster.has_subscribers:
            # Lazy import keeps cv2 out of pipeline-module import graphs that
            # don't need it (e.g. unit tests with fake frames).
            from edge.dashboard.annotate import annotate_and_encode  # noqa: PLC0415

            try:
                jpeg = await anyio.to_thread.run_sync(
                    partial(
                        annotate_and_encode,
                        frame.image,
                        bird_count=detection_filled.bird_count,
                        density=detection_filled.density_score,
                        confidence=detection_filled.confidence,
                        huddling=huddling_score,
                        weight_g=weight_g,
                        centroids=list(detection_filled.bbox_centroids),
                    )
                )
                await self._broadcaster.publish(jpeg)
            except Exception as exc:  # noqa: BLE001
                # Streaming is best-effort; never fail the pipeline because
                # the dashboard had a bad frame.
                log.debug("frame.stream.publish_failed", error=str(exc))
