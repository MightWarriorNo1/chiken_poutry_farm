"""ConfigPipeline — polls a config source and fans out to supervisors.

The pipeline is intentionally dumb: it ferries the latest config to whichever
supervisors are wired in. If `fetch()` returns None (no change), state is
preserved. Each supervisor's `apply()` is responsible for being idempotent.
"""

from __future__ import annotations

from typing import Any

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

    async def _apply(self, config: dict[str, Any]) -> None:
        # Inference first — a new detector will be ready before any camera tries to use it.
        if self._inference is not None:
            await self._inference.apply(config.get("ai") or {})

        cameras = config.get("cameras") or []
        await self._cameras.apply(cameras)
        log.info(
            "config.applied",
            cameras=len(cameras),
            bird_model=self._inference.current_version if self._inference else None,
        )
