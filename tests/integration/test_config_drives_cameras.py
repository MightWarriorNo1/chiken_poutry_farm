"""End-to-end: YamlConfigSource → ConfigPipeline → CameraSupervisor → FramePipeline.

Uses the StubBirdDetector so the test doesn't require a real model or video file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anyio
import pytest

from edge.capture.source import Frame, FrameSource
from edge.config_sources.yaml_config_source import YamlConfigSource
from edge.domain.events import EventType
from edge.inference.models.stub_detector import StubBirdDetector
from edge.outbox.sqlite_outbox import SqliteOutbox
from edge.pipelines.config_pipeline import ConfigPipeline
from edge.pipelines.frame_pipeline import FramePipeline
from edge.supervisors.camera_supervisor import CameraSupervisor


class _SyntheticSource:
    """In-memory frame source — no cv2, no disk, no network. Emits 5 frames fast."""

    def __init__(self, camera_id: str) -> None:
        self.camera_id = camera_id

    async def open(self) -> None: ...
    async def close(self) -> None: ...

    async def frames(self):
        from datetime import datetime, timezone
        for i in range(5):
            yield Frame(
                camera_id=self.camera_id,
                captured_at=datetime.now(timezone.utc),
                width=640,
                height=480,
                image=None,
                sequence=i,
            )
            await anyio.sleep(0.01)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_config_starts_camera_and_detections_land_in_outbox(tmp_path: Path) -> None:
    outbox = SqliteOutbox(tmp_path / "ob.db")
    await outbox.init()

    config_yaml = tmp_path / "edge.yaml"
    config_yaml.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "device_id": "edge-test",
                "cameras": [
                    {
                        "camera_id": "cam-test",
                        "source_uri": "file://./placeholder",  # ignored: factory below
                        "role": "general",
                        "shed_id": "shed-1",
                        "flock_id": "flock-A",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    detector = StubBirdDetector(seed=7)

    def factory(cfg: dict[str, Any]) -> FramePipeline:
        # Override the URI-based capture factory with an in-memory one for the test.
        source: FrameSource = _SyntheticSource(camera_id=cfg["camera_id"])
        return FramePipeline(
            device_id="edge-test",
            source=source,
            bird_detector=detector,
            outbox=outbox,
            flock_id=cfg.get("flock_id"),
            shed_id=cfg.get("shed_id"),
        )

    try:
        async with anyio.create_task_group() as tg:
            sup = CameraSupervisor(task_group=tg, factory=factory)
            pipe = ConfigPipeline(
                source=YamlConfigSource(config_yaml),
                camera_supervisor=sup,
                poll_interval_seconds=60,
            )
            tg.start_soon(pipe.run)
            await anyio.sleep(0.3)  # let config pipeline fire + frames flow
            tg.cancel_scope.cancel()

        detections = await outbox.peek(EventType.BIRD_DETECTION, 100)
        assert len(detections) >= 3, f"expected detections, got {len(detections)}"
        sample = detections[0]
        assert sample.payload["device_id"] == "edge-test"
        assert sample.payload["camera_id"] == "cam-test"
        assert sample.payload["shed_id"] == "shed-1"
        assert sample.payload["flock_id"] == "flock-A"
        assert sample.payload["bird_count"] > 0
    finally:
        await outbox.close()
