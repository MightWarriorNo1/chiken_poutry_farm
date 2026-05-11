"""Port: dashboard read model.

The read model is a *projection* of the event stream — the latest state per
camera / sensor / device plus rolling windows for alerts, manual weights, and
sparkline series.

It exists because the outbox is FIFO-and-drain: events are deleted from
`outbox.db` after successful cloud sync, so reading the outbox to power a
dashboard would mostly show "nothing here". The projection keeps a durable
snapshot keyed by entity, independent of sync.

Concrete impl in [`sqlite_read_model.py`](sqlite_read_model.py). Production
could swap to an in-memory dict or Redis without touching pipelines.
"""

from __future__ import annotations

from typing import Protocol

from edge.dashboard.views import (
    AlertView,
    CameraSeriesView,
    CameraView,
    ManualWeightView,
    SensorSeriesView,
    SensorView,
    StatusView,
)
from edge.domain.events import EventEnvelope


class ReadModel(Protocol):
    """Tee-target for [`ProjectingOutbox`]."""

    async def init(self) -> None: ...

    async def close(self) -> None: ...

    async def apply(self, event: EventEnvelope) -> None:
        """Update the projection from one event. Must never raise — events
        keep flowing through the outbox even if a projection update fails."""

    # ── queries (consumed by the FastAPI layer) ──────────────────────────────

    async def get_status(self) -> StatusView: ...

    async def list_cameras(self) -> list[CameraView]: ...

    async def get_camera_series(self, camera_id: str, limit: int) -> CameraSeriesView: ...

    async def list_sensors(self) -> list[SensorView]: ...

    async def get_sensor_series(self, sensor_id: str, limit: int) -> SensorSeriesView: ...

    async def list_alerts(self, limit: int) -> list[AlertView]: ...

    async def list_manual_weights(self, limit: int) -> list[ManualWeightView]: ...
