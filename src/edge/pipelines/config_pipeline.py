"""ConfigPipeline — polls a config source and fans changes out to supervisors.

Currently feeds `cameras` to CameraSupervisor and `ai` to InferenceSupervisor.
SensorSupervisor lands in Sprint 4 with the same pattern. If `fetch()` returns
None, the current state is preserved.

AI config is applied *before* cameras so that when a new camera starts the
matching detector is already in place.
"""

from __future__ import annotations

import anyio
import structlog

from edge.config_sources.source import EdgeConfigSource
from edge.supervisors.camera_supervisor import CameraSupervisor
from edge.supervisors.inference_supervisor import InferenceSupervisor

log = structlog.get_logger(__name__)


class ConfigPipeline:
    def __init__(
        self,
        source: EdgeConfigSource,
        camera_supervisor: CameraSupervisor,
        inference_supervisor: InferenceSupervisor | None = None,
        poll_interval_seconds: int = 300,
    ) -> None:
        self._source = source
        self._cameras = camera_supervisor
        self._inference = inference_supervisor
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
        if self._inference is not None:
            ai_cfg = config.get("ai") or {}
            await self._inference.apply(ai_cfg)

        cameras = config.get("cameras") or []
        await self._cameras.apply(cameras)

        log.info(
            "config.applied",
            cameras=len(cameras),
            ai_active=self._inference.model_version if self._inference else None,
        )
