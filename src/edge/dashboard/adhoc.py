"""Ad-hoc camera manager — one user-initiated camera at a time.

Sibling to `DemoManager`. The dashboard's "Sources" tab lets a user pick a
camera type (USB/CSI/RTSP/File), see what the device auto-discovers, and
click one to start streaming. That click drops a camera config into the
CameraSupervisor's `extras` overlay with `role: "adhoc"` — which routes
events through the demo_outbox path (no cloud sync) but still feeds the
read model + event bus (so the dashboard updates live).

Stopping reverses it. One ad-hoc at a time, by design.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import anyio
import structlog

from edge.dashboard.views import AdhocStatusView
from edge.supervisors.camera_supervisor import CameraSupervisor

log = structlog.get_logger(__name__)

ADHOC_CAMERA_ID = "adhoc"


@dataclass(slots=True)
class _AdhocJob:
    source_type: str
    source_uri: str
    label: str
    started_at: datetime


class AdhocManager:
    """One-at-a-time ad-hoc camera, started from the dashboard's Sources tab."""

    def __init__(
        self,
        *,
        camera_supervisor: CameraSupervisor,
    ) -> None:
        self._supervisor = camera_supervisor
        self._lock = anyio.Lock()
        self._current: _AdhocJob | None = None

    async def start(
        self,
        *,
        source_type: str,
        source_uri: str,
        label: str | None = None,
    ) -> AdhocStatusView:
        if not source_uri:
            raise ValueError("source_uri is required")

        async with self._lock:
            if self._current is not None:
                raise RuntimeError(
                    f"Ad-hoc camera already running ({self._current.label}); stop it first."
                )

            display = label or source_uri
            self._current = _AdhocJob(
                source_type=source_type,
                source_uri=source_uri,
                label=display,
                started_at=datetime.now(timezone.utc),
            )

            cam_cfg: dict[str, Any] = {
                "camera_id": ADHOC_CAMERA_ID,
                "source_uri": source_uri,
                "role": "adhoc",
                "shed_id": "adhoc",
                "zone_id": "adhoc",
                "flock_id": "adhoc-flock",
                "flock_age_days": 30,
                "breed": "ross_308",
                # Demo videos picked through this path should not loop.
                "loop": not source_uri.startswith("file://"),
            }
            log.info(
                "adhoc.start",
                source_type=source_type,
                source_uri=source_uri,
                label=display,
            )

        await self._supervisor.set_extras([cam_cfg])
        return await self.status()

    async def stop(self) -> AdhocStatusView:
        async with self._lock:
            if self._current is None:
                return AdhocStatusView(running=False)
            label = self._current.label
            self._current = None
            log.info("adhoc.stop", label=label)
        await self._supervisor.set_extras([])
        return await self.status()

    async def status(self) -> AdhocStatusView:
        async with self._lock:
            running = (
                self._current is not None
                and ADHOC_CAMERA_ID in self._supervisor.running_cameras
            )
            if not running or self._current is None:
                return AdhocStatusView(running=False)

            elapsed = (datetime.now(timezone.utc) - self._current.started_at).total_seconds()
            return AdhocStatusView(
                running=True,
                camera_id=ADHOC_CAMERA_ID,
                source_type=self._current.source_type,
                source_uri=self._current.source_uri,
                label=self._current.label,
                started_at=self._current.started_at,
                elapsed_seconds=elapsed,
                stream_url=f"/api/cameras/{ADHOC_CAMERA_ID}/stream",
            )
