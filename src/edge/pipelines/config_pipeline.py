"""ConfigPipeline — polls a config source and feeds the camera supervisor.

The pipeline is intentionally dumb: it ferries `cameras` from the latest config
to the supervisor. (Sensors come from a different supervisor in Sprint 4; same
pattern.) If `fetch()` returns None, the current state is preserved.
"""

from __future__ import annotations

import anyio
import structlog

from edge.config_sources.source import EdgeConfigSource
from edge.supervisors.camera_supervisor import CameraSupervisor

log = structlog.get_logger(__name__)


class ConfigPipeline:
    def __init__(
        self,
        source: EdgeConfigSource,
        camera_supervisor: CameraSupervisor,
        poll_interval_seconds: int = 300,
    ) -> None:
        self._source = source
        self._cameras = camera_supervisor
        self._poll_interval = poll_interval_seconds

    async def run(self) -> None:
        while True:
            try:
                config = await self._source.fetch()
                if config is not None:
                    await self._apply(config)
            except Exception as exc:  # noqa: BLE001
                log.exception("config.apply.failed", error=str(exc))
            await anyio.sleep(self._poll_interval)

    async def _apply(self, config: dict) -> None:
        cameras = config.get("cameras") or []
        await self._cameras.apply(cameras)
        log.info("config.applied", cameras=len(cameras))
