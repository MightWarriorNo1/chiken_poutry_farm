"""EdgeBox composition root.

This is the only file allowed to know about *all* the moving parts. Pipelines and
adapters are wired here based on config; everything below this layer is loosely
coupled and unit-testable in isolation.
"""

from __future__ import annotations

import signal
from pathlib import Path

import anyio
import structlog

from edge.config import Settings, load_settings
from edge.outbox.sqlite_outbox import SqliteOutbox
from edge.pipelines.heartbeat_pipeline import HeartbeatPipeline
from edge.pipelines.sensor_pipeline import SensorPipeline
from edge.pipelines.sync_pipeline import SyncPipeline
from edge.sensors.simulator import SimulatedSensorReader
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

    # Sensors: simulator by default; swap to MQTT once a broker is configured.
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

    # Frame pipelines come online once cameras + models are configured (Sprint 1+).
    # The structure is identical: build N FramePipeline instances and `tg.start_soon` each.

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(sensor_pipe.run)
            tg.start_soon(heartbeat_pipe.run)
            tg.start_soon(sync_pipe.run)
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


# Keep the import surface tidy for tests.
__all__ = ["amain", "run", "Path"]
