"""DashboardPipeline — hosts the FastAPI dashboard inside the edge process.

Running uvicorn in the same anyio task group as the other pipelines means:
  - One log stream, one shutdown signal handler.
  - The SQLite connection is shared (well: the read model has its own, but
    same file with WAL — no contention worth worrying about at PoC volumes).
  - A `tg.cancel_scope.cancel()` from `_install_signal_handler` cancels the
    server too.

We pass `install_signal_handlers=False` to uvicorn because the edge runtime
already owns SIGINT/SIGTERM via `_install_signal_handler` in main.py.
"""

from __future__ import annotations

from pathlib import Path

import structlog
import uvicorn

from edge.config import DashboardSettings
from edge.dashboard.adhoc import AdhocManager
from edge.dashboard.demo import DemoManager
from edge.dashboard.event_bus import EventBus
from edge.dashboard.read_model import ReadModel
from edge.dashboard.server import (
    ThresholdProvider,
    create_app,
)
from edge.dashboard.stream_registry import StreamRegistry
from edge.supervisors.camera_supervisor import CameraSupervisor

log = structlog.get_logger(__name__)


class DashboardPipeline:
    def __init__(
        self,
        *,
        read_model: ReadModel,
        event_bus: EventBus,
        settings: DashboardSettings,
        threshold_provider: ThresholdProvider,
        static_dir: Path | None,
        stream_registry: StreamRegistry | None = None,
        camera_supervisor: CameraSupervisor | None = None,
        demo_manager: DemoManager | None = None,
        adhoc_manager: AdhocManager | None = None,
        demo_videos_dir: Path | None = None,
    ) -> None:
        self._read_model = read_model
        self._event_bus = event_bus
        self._settings = settings
        self._threshold_provider = threshold_provider
        self._static_dir = static_dir
        self._stream_registry = stream_registry
        self._camera_supervisor = camera_supervisor
        self._demo_manager = demo_manager
        self._adhoc_manager = adhoc_manager
        self._demo_videos_dir = demo_videos_dir

    async def run(self) -> None:
        app = create_app(
            read_model=self._read_model,
            event_bus=self._event_bus,
            settings=self._settings,
            threshold_provider=self._threshold_provider,
            static_dir=self._static_dir,
            stream_registry=self._stream_registry,
            camera_supervisor=self._camera_supervisor,
            demo_manager=self._demo_manager,
            adhoc_manager=self._adhoc_manager,
            demo_videos_dir=self._demo_videos_dir,
        )

        config = uvicorn.Config(
            app,
            host=self._settings.host,
            port=self._settings.port,
            log_level="info",
            log_config=None,           # let structlog own the log surface
            access_log=False,          # noisy for an internal dashboard
            lifespan="on",
            loop="asyncio",
        )
        server = uvicorn.Server(config)
        # main.py owns SIGINT/SIGTERM via _install_signal_handler. Suppress
        # uvicorn's handlers so the two installers don't clash. (Method-level
        # override is the documented pattern; in uvicorn ≥ 0.30 there is no
        # `install_signal_handlers` kwarg on Config.)
        server.install_signal_handlers = lambda: None  # type: ignore[method-assign]

        log.info(
            "dashboard.serving",
            url=f"http://{self._settings.host}:{self._settings.port}",
        )
        try:
            await server.serve()
        finally:
            log.info("dashboard.stopped")
