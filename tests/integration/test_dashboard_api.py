"""End-to-end: events written to the wrapped outbox show up in the HTTP API.

Goes through:
  ProjectingOutbox.put(...) → SqliteReadModel.apply(...) → SQLite
                          ↘ EventBus.publish(...) → (SSE — covered in Phase 4)

Then exercises every /api endpoint via the ASGI transport.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from edge.config import DashboardSettings
from edge.dashboard.event_bus import EventBus
from edge.dashboard.projecting_outbox import ProjectingOutbox
from edge.dashboard.server import create_app
from edge.dashboard.sqlite_read_model import SqliteReadModel
from edge.domain.events import EventEnvelope, EventType


class _NullInner:
    """Inner outbox stub: durability already tested elsewhere; we just need
    `put` to be a no-op for the ProjectingOutbox tee path."""
    async def init(self): ...
    async def close(self): ...
    async def put(self, _ev): ...
    async def peek(self, *_): return []
    async def ack(self, _): ...
    async def nack(self, _): ...
    async def pending_count(self): return 0


async def _seed_full(outbox: ProjectingOutbox) -> None:
    """Write one of every event type so the API has something to return."""
    ts = datetime(2026, 5, 11, 9, 0, tzinfo=timezone.utc).isoformat()
    await outbox.put(EventEnvelope(
        event_type=EventType.DEVICE_HEARTBEAT,
        payload={
            "device_id": "edge-1",
            "reported_at": ts,
            "status": "healthy",
            "software_version": "0.1.0",
            "cpu_pct": 18.5,
            "memory_pct": 32.0,
            "storage_pct": 11.0,
            "outbox_pending": 3,
            "ai_models": [{"name": "bird-detector", "version": "1.0.0"}],
        },
    ))
    await outbox.put(EventEnvelope(
        event_type=EventType.BIRD_DETECTION,
        payload={
            "camera_id": "cam-1",
            "shed_id": "shed-A",
            "flock_id": "flock-A",
            "captured_at": ts,
            "model_version": "bird-detector@stub-0.0.1",
            "bird_count": 90,
            "density_score": 0.6,
            "confidence": 0.88,
        },
    ))
    await outbox.put(EventEnvelope(
        event_type=EventType.WEIGHT_ESTIMATE,
        payload={
            "camera_id": "cam-1",
            "flock_id": "flock-A",
            "captured_at": ts,
            "estimated_avg_weight_g": 1620,
            "confidence": 0.32,
            "bird_age_days": 28,
            "breed": "ross_308",
        },
    ))
    await outbox.put(EventEnvelope(
        event_type=EventType.HUDDLING_SCORE,
        payload={
            "camera_id": "cam-1",
            "zone_id": "zone-A",
            "captured_at": ts,
            "huddling_score": 0.42,
            "cluster_count": 1,
            "largest_cluster_pct": 0.42,
        },
    ))
    await outbox.put(EventEnvelope(
        event_type=EventType.SENSOR_READING,
        payload={
            "sensor_id": "temp-1",
            "sensor_type": "temperature",
            "shed_id": "shed-A",
            "value": 22.5,
            "unit": "celsius",
            "recorded_at": ts,
        },
    ))
    await outbox.put(EventEnvelope(
        event_type=EventType.SENSOR_READING,
        payload={
            "sensor_id": "temp-1",
            "sensor_type": "temperature",
            "value": 31.0,  # above max=30 — should mark out-of-range
            "unit": "celsius",
            "recorded_at": ts,
        },
    ))
    await outbox.put(EventEnvelope(
        event_type=EventType.ALERT,
        payload={
            "event_id": str(uuid4()),
            "alert_type": "sensor_out_of_range",
            "severity": "high",
            "source": "sensor",
            "raised_at": ts,
            "message": "Temperature 31.0 above max 30",
            "sensor_id": "temp-1",
        },
    ))
    await outbox.put(EventEnvelope(
        event_type=EventType.MANUAL_WEIGHT_SAMPLE,
        payload={
            "event_id": str(uuid4()),
            "flock_id": "flock-A",
            "sampled_at": ts,
            "flock_age_days": 28,
            "sample_count": 50,
            "average_weight_g": 1610.5,
        },
    ))


async def _setup(tmp_path: Path):
    rm = SqliteReadModel(tmp_path / "view.db")
    await rm.init()
    bus = EventBus()
    outbox = ProjectingOutbox(inner=_NullInner(), read_model=rm, event_bus=bus)
    app = create_app(
        read_model=rm,
        event_bus=bus,
        settings=DashboardSettings(),
        threshold_provider=lambda: {"temp-1": (18.0, 30.0)},
    )
    return rm, bus, outbox, app


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_status_reflects_heartbeat(tmp_path: Path) -> None:
    rm, _bus, outbox, app = await _setup(tmp_path)
    try:
        await _seed_full(outbox)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/status")
        assert r.status_code == 200
        body = r.json()
        assert body["device_id"] == "edge-1"
        assert body["status"] == "healthy"
        assert body["cpu_pct"] == 18.5
        assert body["camera_count"] == 1
        assert body["sensor_count"] == 1
        assert body["open_alert_count"] == 1
    finally:
        await rm.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_cameras_join_detection_weight_huddling(tmp_path: Path) -> None:
    rm, _bus, outbox, app = await _setup(tmp_path)
    try:
        await _seed_full(outbox)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/cameras")
        assert r.status_code == 200
        cams = r.json()
        assert len(cams) == 1
        cam = cams[0]
        assert cam["camera_id"] == "cam-1"
        assert cam["bird_count"] == 90
        assert cam["huddling_score"] == 0.42
        assert cam["estimated_avg_weight_g"] == 1620
        assert cam["breed"] == "ross_308"
    finally:
        await rm.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_sensors_includes_thresholds_and_range(tmp_path: Path) -> None:
    rm, _bus, outbox, app = await _setup(tmp_path)
    try:
        await _seed_full(outbox)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/api/sensors")
        assert r.status_code == 200
        sensors = r.json()
        assert len(sensors) == 1
        s = sensors[0]
        assert s["sensor_id"] == "temp-1"
        assert s["value"] == 31.0
        assert s["threshold_min"] == 18.0
        assert s["threshold_max"] == 30.0
        assert s["in_range"] is False
    finally:
        await rm.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_alerts_and_manual_weights(tmp_path: Path) -> None:
    rm, _bus, outbox, app = await _setup(tmp_path)
    try:
        await _seed_full(outbox)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            ar = await client.get("/api/alerts")
            mr = await client.get("/api/manual-weights")
        assert ar.status_code == 200
        assert mr.status_code == 200
        assert len(ar.json()) == 1
        assert ar.json()[0]["alert_type"] == "sensor_out_of_range"
        assert len(mr.json()) == 1
        assert mr.json()[0]["average_weight_g"] == 1610.5
    finally:
        await rm.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_root_placeholder_when_no_react_build(tmp_path: Path) -> None:
    rm, _bus, _outbox, app = await _setup(tmp_path)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/")
        assert r.status_code == 200
        body = r.json()
        assert "endpoints" in body
        assert "/api/status" in body["endpoints"]
    finally:
        await rm.close()
