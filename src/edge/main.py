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

from edge.alerts.alerting_outbox import AlertingOutbox
from edge.alerts.engine import AlertEngine
from edge.alerts.rules import (
    CameraOfflineRule,
    HighHuddlingRule,
    SensorOutOfRangeRule,
    WeightBelowTargetRule,
)
from edge.capture.factory import build_frame_source
from edge.config import Settings, load_settings
from edge.config_sources.http_config_source import HttpConfigSource
from edge.config_sources.source import EdgeConfigSource
from edge.config_sources.yaml_config_source import YamlConfigSource
from edge.dashboard.adhoc import AdhocManager
from edge.dashboard.demo import DemoManager
from edge.dashboard.event_bus import EventBus
from edge.dashboard.projecting_outbox import ProjectingOutbox
from edge.dashboard.server import threshold_provider_from_supervisor
from edge.dashboard.sqlite_read_model import SqliteReadModel
from edge.dashboard.stream_registry import StreamRegistry
from edge.inference.factory import (
    build_bird_detector,
    build_huddling_detector,
    build_weight_estimator,
)
from edge.inference.model_loader import ModelLoader
from edge.inference.models.stub_detector import StubBirdDetector
from edge.inference.models.stub_huddling import StubHuddlingDetector
from edge.inference.models.stub_weight_estimator import StubWeightEstimator
from edge.inference.proxied_detector import DetectorRegistry, ProxiedBirdDetector
from edge.inference.proxied_estimator import EstimatorRegistry, ProxiedWeightEstimator
from edge.inference.proxied_huddling import HuddlingRegistry, ProxiedHuddlingDetector
from edge.outbox.null_outbox import NullOutbox
from edge.outbox.sqlite_outbox import SqliteOutbox
from edge.pipelines.config_pipeline import ConfigPipeline
from edge.pipelines.frame_pipeline import FramePipeline
from edge.pipelines.heartbeat_pipeline import HeartbeatPipeline
from edge.pipelines.sensor_pipeline import SensorPipeline
from edge.pipelines.sync_pipeline import SyncPipeline
from edge.sensors.factory import build_sensor_reader
from edge.supervisors.alert_supervisor import AlertSupervisor
from edge.supervisors.camera_supervisor import CameraSupervisor
from edge.supervisors.inference_supervisor import InferenceSupervisor, ModelHandler
from edge.supervisors.sensor_supervisor import SensorSupervisor
from edge.sync.http_sync import HttpCloudSync
from edge.telemetry import configure as configure_telemetry

log = structlog.get_logger("edge.main")


async def amain(settings: Settings) -> None:
    log.info(
        "edge.starting",
        device_id=settings.device_id,
        version=settings.software_version,
    )

    inner_outbox = SqliteOutbox(settings.storage.outbox_path)
    await inner_outbox.init()

    # Cloud is optional — when disabled, no HTTP client is opened, no
    # SyncPipeline runs, and events accumulate locally in the SqliteOutbox.
    cloud: HttpCloudSync | None = None
    if settings.cloud.enabled:
        cloud = HttpCloudSync(settings.cloud)
        await cloud.start()
        log.info("cloud.enabled", base_url=settings.cloud.base_url)
    else:
        log.info("cloud.disabled", reason="EDGE_CLOUD__ENABLED=false")

    # ── Alerts: rules + engine + outbox wrapper ────────────────────────────
    sensor_oor_rule = SensorOutOfRangeRule(device_id=settings.device_id)
    alert_rules = [
        CameraOfflineRule(device_id=settings.device_id, threshold_seconds=60.0),
        sensor_oor_rule,
        HighHuddlingRule(device_id=settings.device_id, threshold=0.7, consecutive_frames=3),
        WeightBelowTargetRule(device_id=settings.device_id, threshold_pct=0.15),
    ]
    alert_engine = AlertEngine(outbox=inner_outbox, rules=alert_rules)
    alert_sup = AlertSupervisor(sensor_out_of_range=sensor_oor_rule)

    # ── Local dashboard: read model + event bus + outbox tee ───────────────
    read_model = SqliteReadModel(
        settings.storage.outbox_path,
        series_size=settings.dashboard.series_size,
        alerts_window=settings.dashboard.alerts_window,
        manual_weights_window=settings.dashboard.manual_weights_window,
    )
    await read_model.init()
    event_bus = EventBus(max_queue=128)
    # Per-camera MJPEG broadcaster registry. Frame pipelines publish JPEGs;
    # the dashboard server subscribes when a browser opens the live view.
    stream_registry = StreamRegistry()

    # Outbox composition order matters: pipelines write through the OUTERMOST
    # wrapper. AlertingOutbox runs the alert engine; ProjectingOutbox tees into
    # the read model + SSE bus. Both wrap the durable SqliteOutbox.
    alerting = AlertingOutbox(inner=inner_outbox, engine=alert_engine)
    outbox = ProjectingOutbox(
        inner=alerting,
        read_model=read_model,
        event_bus=event_bus,
    )

    # Demo outbox: same dashboard tee + alert engine, but a no-op at the bottom
    # so demo events never reach SqliteOutbox → never picked up by SyncPipeline
    # → never reach the cloud. The dashboard still sees everything.
    demo_inner = NullOutbox()
    demo_alerting = AlertingOutbox(inner=demo_inner, engine=alert_engine)
    demo_outbox = ProjectingOutbox(
        inner=demo_alerting,
        read_model=read_model,
        event_bus=event_bus,
    )

    # ── Inference: stub on boot, hot-swappable per model name from EdgeConfig.ai.models ──
    detector_registry = DetectorRegistry(initial=StubBirdDetector(seed=None))
    proxied_detector = ProxiedBirdDetector(detector_registry)
    estimator_registry = EstimatorRegistry(initial=StubWeightEstimator())
    proxied_estimator = ProxiedWeightEstimator(estimator_registry)
    huddling_registry = HuddlingRegistry(initial=StubHuddlingDetector())
    proxied_huddling = ProxiedHuddlingDetector(huddling_registry)
    model_loader = ModelLoader(models_root=Path("./models"))
    inference_sup = InferenceSupervisor(
        loader=model_loader,
        handlers={
            "bird-detector": ModelHandler(
                build=build_bird_detector,
                install=detector_registry.swap,
            ),
            "weight-estimator": ModelHandler(
                build=build_weight_estimator,
                install=estimator_registry.swap,
            ),
            "huddling-detector": ModelHandler(
                build=build_huddling_detector,
                install=huddling_registry.swap,
            ),
        },
    )

    # Sensors are now config-driven via SensorSupervisor (built inside the task group).
    heartbeat_pipe = HeartbeatPipeline(
        device_id=settings.device_id,
        software_version=settings.software_version,
        outbox=outbox,
        interval_seconds=settings.cadence.heartbeat_interval_seconds,
    )
    # Sync drains the inner outbox directly — only built when cloud is enabled.
    sync_pipe: SyncPipeline | None = None
    if cloud is not None:
        sync_pipe = SyncPipeline(
            outbox=inner_outbox,
            cloud=cloud,
            batch_size=settings.cadence.sync_batch_size,
            flush_interval_seconds=settings.cadence.sync_flush_interval_seconds,
        )

    # ── Config source: prefer static YAML when set, else poll the cloud ─────
    # With cloud disabled, a static_config_path is mandatory — there's no
    # other way to learn about cameras/sensors/AI models.
    config_source: EdgeConfigSource
    if settings.static_config_path is not None:
        log.info("config.source", kind="yaml", path=str(settings.static_config_path))
        config_source = YamlConfigSource(settings.static_config_path)
    elif cloud is not None:
        log.info("config.source", kind="http", base_url=settings.cloud.base_url)
        config_source = HttpConfigSource(cloud)
    else:
        raise RuntimeError(
            "No EdgeConfig source: cloud is disabled (EDGE_CLOUD__ENABLED=false) "
            "and EDGE_STATIC_CONFIG_PATH is not set. Set one or the other."
        )

    # ── Run ────────────────────────────────────────────────────────────────
    try:
        async with anyio.create_task_group() as tg:
            target_fps = 1.0 / max(settings.cadence.frame_interval_seconds, 0.1)

            def make_frame_pipeline(cam_cfg: dict[str, Any]) -> FramePipeline:
                source = build_frame_source(cam_cfg, target_fps=target_fps)
                broadcaster = stream_registry.get_or_create(cam_cfg["camera_id"])
                # Demo and ad-hoc cameras both bypass cloud sync — they share
                # the same NullOutbox-backed chain. Production cameras use the
                # durable outbox that SyncPipeline drains.
                role = cam_cfg.get("role")
                target_outbox = demo_outbox if role in ("demo", "adhoc") else outbox
                return FramePipeline(
                    device_id=settings.device_id,
                    source=source,
                    bird_detector=proxied_detector,
                    weight_estimator=proxied_estimator,
                    huddling_detector=proxied_huddling,
                    outbox=target_outbox,
                    shed_id=cam_cfg.get("shed_id"),
                    flock_id=cam_cfg.get("flock_id"),
                    flock_age_days=cam_cfg.get("flock_age_days"),
                    breed=cam_cfg.get("breed"),
                    broadcaster=broadcaster,
                )

            def make_sensor_pipeline(
                protocol: str, sensor_cfgs: list[dict[str, Any]]
            ) -> SensorPipeline:
                reader = build_sensor_reader(
                    protocol,
                    sensor_cfgs,
                    device_id=settings.device_id,
                    mqtt=settings.mqtt,
                    modbus=settings.modbus,
                )
                return SensorPipeline(reader=reader, outbox=outbox)

            camera_sup = CameraSupervisor(task_group=tg, factory=make_frame_pipeline)
            sensor_sup = SensorSupervisor(task_group=tg, factory=make_sensor_pipeline)

            demo_videos_dir = Path("demo/recordings")
            # DemoManager hooks the supervisor's completion callback in __init__
            # so a finished demo video clears the extras overlay automatically.
            demo_manager = DemoManager(
                videos_dir=demo_videos_dir,
                camera_supervisor=camera_sup,
                read_model=read_model,
            )
            # AdhocManager handles user-initiated ad-hoc cameras (Sources tab).
            # Both demo and adhoc compete for the supervisor's single `extras`
            # slot — starting one while the other is running returns 409.
            adhoc_manager = AdhocManager(camera_supervisor=camera_sup)

            config_pipe = ConfigPipeline(
                source=config_source,
                camera_supervisor=camera_sup,
                inference_supervisor=inference_sup,
                sensor_supervisor=sensor_sup,
                alert_supervisor=alert_sup,
                poll_interval_seconds=settings.cadence.config_poll_interval_seconds,
            )

            tg.start_soon(heartbeat_pipe.run)
            if sync_pipe is not None:
                tg.start_soon(sync_pipe.run)
            tg.start_soon(alert_engine.run)
            tg.start_soon(config_pipe.run)

            if settings.dashboard.enabled:
                # Import lazily so the `dashboard` extra isn't a hard dep.
                from edge.pipelines.dashboard_pipeline import DashboardPipeline  # noqa: PLC0415

                static_dir = Path(__file__).parent / "dashboard" / "web" / "dist"
                dashboard_pipe = DashboardPipeline(
                    read_model=read_model,
                    event_bus=event_bus,
                    settings=settings.dashboard,
                    threshold_provider=threshold_provider_from_supervisor(sensor_sup),
                    static_dir=static_dir if static_dir.is_dir() else None,
                    stream_registry=stream_registry,
                    camera_supervisor=camera_sup,
                    demo_manager=demo_manager,
                    adhoc_manager=adhoc_manager,
                    demo_videos_dir=demo_videos_dir,
                )
                tg.start_soon(dashboard_pipe.run)

            tg.start_soon(_install_signal_handler, tg.cancel_scope)
    finally:
        if cloud is not None:
            await cloud.close()
        await read_model.close()
        await inner_outbox.close()
        log.info("edge.stopped")


async def _install_signal_handler(cancel_scope: anyio.CancelScope) -> None:
    try:
        with anyio.open_signal_receiver(signal.SIGINT, signal.SIGTERM) as signals:
            async for sig in signals:
                log.info("edge.signal", signal=sig)
                cancel_scope.cancel()
                return
    except NotImplementedError:
        # Windows + asyncio doesn't support `add_signal_handler`. We rely on
        # `KeyboardInterrupt` propagating up through `run()` instead.
        log.info("edge.signal_receiver.unsupported", platform="windows")


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
