"""Cloud-polled config source — uses ETag for cheap polling."""

from __future__ import annotations

from typing import Any

import structlog

from edge.sync.sync import CloudSync

log = structlog.get_logger(__name__)


class HttpConfigSource:
    def __init__(self, cloud: CloudSync) -> None:
        self._cloud = cloud
        self._etag: str | None = None

    async def fetch(self) -> dict[str, Any] | None:
        try:
            config, etag = await self._cloud.fetch_config(self._etag)
        except Exception as exc:  # noqa: BLE001
            log.warning("config.fetch.failed", error=str(exc))
            return None

        if config is None:
            return None  # 304 Not Modified — nothing to apply

        self._etag = etag
        return config
