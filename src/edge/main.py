"""EdgeBox composition root.

This is the only file allowed to know about *all* the moving parts. Pipelines and
adapters are wired here based on config; everything below this layer is loosely
coupled and unit-testable in isolation.

Pipelines started at boot:
  - SensorPipeline     simulator → outbox
  - HeartbeatPipeline  every N seconds → outbox
  - SyncPipeline       outbox → cloud
  - ConfigPipeline     edge config → CameraSupervisor
The CameraSupervisor in turn starts/stops one FramePipeline per configured camera.
"""

from __future__ import annotations

import signal
from pathlib import Path
from typing import Any

import anyio
import structlog

from edge.capture.factory import build_frame_source
from edge.config import Settings, load_settings
from edge.config_sources.http_config_source import HttpConfigSource
from edge.config_sources.source import EdgeConfigSource
from edge.config_sources.yaml_config_source import YamlConfigSource
from edge.inference.model_loader import ModelLoader
from edge.inference.models.stub_detector import StubBirdDetector
from edge.inference.proxied_detector import DetectorRegistry, ProxiedBirdDetector
from edge.outbox.sqlite_outbox import SqliteOutbox
from edge.pipelines.config_pipeline import ConfigPipeline
from edge.pipelines.frame_pipeline import FramePipeline
from edge.pipelines.heartbeat_pipeline import HeartbeatPipeline
from edge.pipelines.sensor_pipeline import SensorPipeline
from edge.pipelines.sync_pipeline import SyncPipeline
from edge.sensors.simulator import SimulatedSensorReader
from edge.supervisors.camera_supervisor import CameraSupervisor
from edge.supervisors.inference_supervisor import InferenceSupervisor
from edge.sync.http_sync import HttpCloudSync
from edge.telemetry import configure as configure_telemetry

log = structlog.get_logger("edge.main")


async def amain(settings: Settings) -> None:
    log.info(
        "edge.starting",
        device_id=settings.device_id,
        version=settings.software_version,
    )

    outbox = SqliteOutbox(settings.storage.outbox_path)
    await outbox.init()

    cloud = HttpCloudSync(settings.cloud)
    await cloud.start()

    # ── Inference: stub on boot, hot-swappable from EdgeConfig.ai.models ────
    detector_registry = DetectorRegistry(initial=StubBirdDetector(seed=None))
    proxied_detector = ProxiedBirdDetector(detector_registry)
    model_loader = ModelLoader(models_root=Path("./models"))
    inference_sup = InferenceSupervisor(detector_registry, model_loader)

    # ── Sensors: simulator by default; swap to MQTT once a broker is configured ──
    sensor_reader = SimulatedSensorReader(device_id=settings.device_id)

    sensor_pipe = SensorPipeline(reader=sensor_reader, outbox=outbox)
    heartbeat_pipe = HeartbeatPipeline(
        device_id=settings.device_id,
        software_version=settings.software_version,
        outbox=outbox,
        interval_seconds=settings.cadence.heartbeat_interval_seconds,
    )
    sync_pipe = SyncPipeline(
        outbox=outbox,
        cloud=cloud,
        batch_size=settings.cadence.sync_batch_size,
        flush_interval_seconds=settings.cadence.sync_flush_interval_seconds,
    )

    # ── Config source: prefer static YAML when set, else poll the cloud ─────
    config_source: EdgeConfigSource
    if settings.static_config_path is not None:
        log.info("config.source", kind="yaml", path=str(settings.static_config_path))
        config_source = YamlConfigSource(settings.static_config_path)
    else:
        log.info("config.source", kind="http", base_url=settings.cloud.base_url)
        config_source = HttpConfigSource(cloud)

    # ── Run ────────────────────────────────────────────────────────────────
    try:
        async with anyio.create_task_group() as tg:
            target_fps = 1.0 / max(settings.cadence.frame_interval_seconds, 0.1)

            def make_frame_pipeline(cam_cfg: dict[str, Any]) -> FramePipeline:
                source = build_frame_source(cam_cfg, target_fps=target_fps)
                return FramePipeline(
                    device_id=settings.device_id,
                    source=source,
                    bird_detector=proxied_detector,
                    outbox=outbox,
                    shed_id=cam_cfg.get("shed_id"),
                    flock_id=cam_cfg.get("flock_id"),
                )

            camera_sup = CameraSupervisor(task_group=tg, factory=make_frame_pipeline)
            config_pipe = ConfigPipeline(
                source=config_source,
                camera_supervisor=camera_sup,
                inference_supervisor=inference_sup,
                poll_interval_seconds=settings.cadence.config_poll_interval_seconds,
            )

            tg.start_soon(sensor_pipe.run)
            tg.start_soon(heartbeat_pipe.run)
            tg.start_soon(sync_pipe.run)
            tg.start_soon(config_pipe.run)
            tg.start_soon(_install_signal_handler, tg.cancel_scope)
    finally:
        await cloud.close()
        await outbox.close()
        log.info("edge.stopped")


async def _install_signal_handler(cancel_scope: anyio.CancelScope) -> None:
    with anyio.open_signal_receiver(signal.SIGINT, signal.SIGTERM) as signals:
        async for sig in signals:
            log.info("edge.signal", signal=sig)
            cancel_scope.cancel()
            return


def run() -> None:
    """Console-script entrypoint (`prosper-edge`)."""
    settings = load_settings()
    configure_telemetry(settings)
    try:
        anyio.run(amain, settings)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
