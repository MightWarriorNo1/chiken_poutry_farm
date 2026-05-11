"""HTTPS+JSON cloud sync adapter.

Endpoint mapping is defined here in one place — easy to align against
contracts/openapi.yaml during reviews.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx
import structlog
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from edge.config import CloudSettings
from edge.domain.events import EventEnvelope, EventType

log = structlog.get_logger(__name__)

# event_type -> path suffix under settings.ingest_path
_INGEST_ROUTES: dict[EventType, str] = {
    EventType.BIRD_DETECTION: "/detections",
    EventType.WEIGHT_ESTIMATE: "/weight-estimates",
    EventType.HUDDLING_SCORE: "/huddling-scores",
    EventType.SENSOR_READING: "/sensor-readings",
    EventType.DEVICE_HEARTBEAT: "/heartbeat",
    EventType.MANUAL_WEIGHT_SAMPLE: "/manual-weights",
}


class HttpCloudSync:
    def __init__(self, settings: CloudSettings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self._settings.base_url,
            timeout=self._settings.request_timeout_seconds,
            headers=self._auth_headers(),
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def send_batch(
        self, event_type: EventType, events: Sequence[EventEnvelope]
    ) -> None:
        if not events:
            return
        if event_type == EventType.DEVICE_HEARTBEAT:
            # heartbeats use a different shape (single object, not a batch)
            for ev in events:
                await self.send_heartbeat(ev.payload)
            return

        suffix = _INGEST_ROUTES[event_type]
        url = self._settings.ingest_path + suffix
        payload = {
            "schema_version": events[0].schema_version,
            "events": [ev.payload for ev in events],
        }
        await self._post_with_retry(url, payload)
        log.info("cloud.ingest.ok", event_type=event_type.value, count=len(events))

    async def send_heartbeat(self, payload: dict) -> None:
        url = self._settings.ingest_path + _INGEST_ROUTES[EventType.DEVICE_HEARTBEAT]
        await self._post_with_retry(url, payload)

    async def fetch_config(self, etag: str | None = None) -> tuple[dict | None, str | None]:
        assert self._client is not None
        headers = {"If-None-Match": etag} if etag else {}
        resp = await self._client.get(self._settings.config_path, headers=headers)
        if resp.status_code == 304:
            return None, etag
        resp.raise_for_status()
        return resp.json(), resp.headers.get("ETag")

    # ── private ────────────────────────────────────────────────────────────
    def _auth_headers(self) -> dict[str, str]:
        token = self._settings.auth_token
        return {"Authorization": f"Bearer {token}"} if token else {}

    async def _post_with_retry(self, url: str, payload: dict) -> None:
        assert self._client is not None
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, max=8),
            retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
            reraise=True,
        ):
            with attempt:
                resp = await self._client.post(url, json=payload)
                if resp.status_code >= 500 or resp.status_code == 429:
                    resp.raise_for_status()  # triggers retry
                resp.raise_for_status()
