"""SqliteReadModel: dispatch, projection state, rolling windows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from edge.dashboard.sqlite_read_model import SqliteReadModel
from edge.domain.events import EventEnvelope, EventType


def _env(event_type: EventType, payload: dict) -> EventEnvelope:
    return EventEnvelope(event_type=event_type, payload=payload)


async def _make_rm(tmp_path: Path, **kwargs) -> SqliteReadModel:
    rm = SqliteReadModel(tmp_path / "view.db", **kwargs)
    await rm.init()
    return rm


@pytest.mark.asyncio
async def test_bird_detection_creates_camera_row_and_series(tmp_path: Path) -> None:
    rm = await _make_rm(tmp_path)
    try:
        now = datetime(2026, 5, 11, 8, 0, tzinfo=timezone.utc)
        await rm.apply(
            _env(
                EventType.BIRD_DETECTION,
                {
                    "event_id": str(uuid4()),
                    "device_id": "edge-1",
                    "camera_id": "cam-1",
                    "shed_id": "shed-A",
                    "flock_id": "flock-A",
                    "zone_id": "zone-1",
                    "captured_at": now.isoformat(),
                    "processed_at": now.isoformat(),
                    "model_version": "bird-detector@stub-0.0.1",
                    "bird_count": 87,
                    "density_score": 0.58,
                    "confidence": 0.91,
                },
            )
        )

        cams = await rm.list_cameras()
        assert len(cams) == 1
        assert cams[0].camera_id == "cam-1"
        assert cams[0].bird_count == 87
        assert cams[0].density_score == pytest.approx(0.58)
        assert cams[0].confidence == pytest.approx(0.91)
        assert cams[0].shed_id == "shed-A"

        series = await rm.get_camera_series("cam-1", limit=10)
        assert len(series.bird_count) == 1
        assert series.bird_count[0].values["count"] == 87.0
        assert series.huddling == []
    finally:
        await rm.close()


@pytest.mark.asyncio
async def test_huddling_event_updates_camera_and_series(tmp_path: Path) -> None:
    rm = await _make_rm(tmp_path)
    try:
        ts = datetime(2026, 5, 11, 8, 5, tzinfo=timezone.utc).isoformat()
        # Seed a bird detection so the camera row exists, then layer huddling on top.
        await rm.apply(
            _env(
                EventType.BIRD_DETECTION,
                {
                    "camera_id": "cam-2",
                    "captured_at": ts,
                    "bird_count": 50,
                    "density_score": 0.4,
                    "confidence": 0.8,
                },
            )
        )
        await rm.apply(
            _env(
                EventType.HUDDLING_SCORE,
                {
                    "camera_id": "cam-2",
                    "zone_id": "zone-2",
                    "captured_at": ts,
                    "huddling_score": 0.75,
                    "cluster_count": 2,
                    "largest_cluster_pct": 0.75,
                },
            )
        )

        cams = await rm.list_cameras()
        assert cams[0].huddling_score == pytest.approx(0.75)
        assert cams[0].cluster_count == 2

        series = await rm.get_camera_series("cam-2", limit=10)
        assert len(series.huddling) == 1
        assert series.huddling[0].values["score"] == pytest.approx(0.75)
    finally:
        await rm.close()


@pytest.mark.asyncio
async def test_weight_estimate_joins_into_camera_view(tmp_path: Path) -> None:
    rm = await _make_rm(tmp_path)
    try:
        ts = datetime(2026, 5, 11, 8, 10, tzinfo=timezone.utc).isoformat()
        await rm.apply(
            _env(
                EventType.BIRD_DETECTION,
                {
                    "camera_id": "cam-3",
                    "captured_at": ts,
                    "bird_count": 100,
                    "density_score": 0.6,
                    "confidence": 0.9,
                },
            )
        )
        await rm.apply(
            _env(
                EventType.WEIGHT_ESTIMATE,
                {
                    "camera_id": "cam-3",
                    "flock_id": "flock-X",
                    "captured_at": ts,
                    "estimated_avg_weight_g": 1620.0,
                    "confidence": 0.36,
                    "bird_age_days": 28,
                    "breed": "ross_308",
                },
            )
        )

        cams = await rm.list_cameras()
        assert cams[0].estimated_avg_weight_g == pytest.approx(1620.0)
        assert cams[0].weight_confidence == pytest.approx(0.36)
        assert cams[0].bird_age_days == 28
        assert cams[0].breed == "ross_308"
    finally:
        await rm.close()


@pytest.mark.asyncio
async def test_sensor_reading_persists_latest_and_series(tmp_path: Path) -> None:
    rm = await _make_rm(tmp_path)
    try:
        for i, v in enumerate([22.5, 23.0, 22.8]):
            ts = (datetime(2026, 5, 11, tzinfo=timezone.utc) + timedelta(seconds=i)).isoformat()
            await rm.apply(
                _env(
                    EventType.SENSOR_READING,
                    {
                        "sensor_id": "temp-1",
                        "sensor_type": "temperature",
                        "value": v,
                        "unit": "celsius",
                        "recorded_at": ts,
                    },
                )
            )

        sensors = await rm.list_sensors()
        assert len(sensors) == 1
        assert sensors[0].value == pytest.approx(22.8)  # latest wins

        series = await rm.get_sensor_series("temp-1", limit=10)
        # Stored oldest → newest after our reversal.
        assert [round(p.values["value"], 1) for p in series.points] == [22.5, 23.0, 22.8]
    finally:
        await rm.close()


@pytest.mark.asyncio
async def test_alert_window_caps_recent(tmp_path: Path) -> None:
    rm = await _make_rm(tmp_path, alerts_window=3)
    try:
        for i in range(5):
            ts = (datetime(2026, 5, 11, tzinfo=timezone.utc) + timedelta(minutes=i)).isoformat()
            await rm.apply(
                _env(
                    EventType.ALERT,
                    {
                        "event_id": str(uuid4()),
                        "alert_type": "sensor_out_of_range",
                        "severity": "high",
                        "source": "sensor",
                        "raised_at": ts,
                        "message": f"alert #{i}",
                    },
                )
            )

        alerts = await rm.list_alerts(limit=10)
        assert len(alerts) == 3
        # Newest first.
        assert alerts[0].message == "alert #4"
        assert alerts[-1].message == "alert #2"
    finally:
        await rm.close()


@pytest.mark.asyncio
async def test_heartbeat_populates_status(tmp_path: Path) -> None:
    rm = await _make_rm(tmp_path)
    try:
        ts = datetime(2026, 5, 11, 8, 0, tzinfo=timezone.utc).isoformat()
        await rm.apply(
            _env(
                EventType.DEVICE_HEARTBEAT,
                {
                    "device_id": "edge-1",
                    "reported_at": ts,
                    "status": "healthy",
                    "software_version": "0.1.0",
                    "cpu_pct": 22.5,
                    "memory_pct": 41.0,
                    "outbox_pending": 7,
                    "ai_models": [
                        {"name": "bird-detector", "version": "1.0.0"},
                        {"name": "huddling-detector", "version": "0.1.0"},
                    ],
                    "cameras": [],
                    "sensors": [],
                },
            )
        )

        status = await rm.get_status()
        assert status.device_id == "edge-1"
        assert status.status == "healthy"
        assert status.cpu_pct == pytest.approx(22.5)
        assert status.outbox_pending == 7
        assert [m.name for m in status.ai_models] == ["bird-detector", "huddling-detector"]
    finally:
        await rm.close()


@pytest.mark.asyncio
async def test_manual_weight_rolling_window(tmp_path: Path) -> None:
    rm = await _make_rm(tmp_path, manual_weights_window=2)
    try:
        for i in range(3):
            ts = (datetime(2026, 5, 11, tzinfo=timezone.utc) + timedelta(hours=i)).isoformat()
            await rm.apply(
                _env(
                    EventType.MANUAL_WEIGHT_SAMPLE,
                    {
                        "event_id": str(uuid4()),
                        "flock_id": "flock-A",
                        "sampled_at": ts,
                        "sample_count": 50,
                        "average_weight_g": 1500.0 + i,
                    },
                )
            )

        samples = await rm.list_manual_weights(limit=10)
        assert len(samples) == 2
        assert samples[0].average_weight_g == pytest.approx(1502.0)
    finally:
        await rm.close()


@pytest.mark.asyncio
async def test_series_size_caps_per_camera(tmp_path: Path) -> None:
    rm = await _make_rm(tmp_path, series_size=3)
    try:
        for i in range(5):
            ts = (datetime(2026, 5, 11, tzinfo=timezone.utc) + timedelta(seconds=i)).isoformat()
            await rm.apply(
                _env(
                    EventType.BIRD_DETECTION,
                    {
                        "camera_id": "cam-cap",
                        "captured_at": ts,
                        "bird_count": i,
                        "density_score": 0.1,
                        "confidence": 0.9,
                    },
                )
            )

        series = await rm.get_camera_series("cam-cap", limit=10)
        assert len(series.bird_count) == 3
        assert [int(p.values["count"]) for p in series.bird_count] == [2, 3, 4]
    finally:
        await rm.close()


@pytest.mark.asyncio
async def test_apply_swallows_bad_payload(tmp_path: Path) -> None:
    """A malformed payload must not raise — events keep flowing."""
    rm = await _make_rm(tmp_path)
    try:
        # Required column `value` missing — SQLite will refuse the insert in
        # `view_series_sensor`; we should still survive.
        await rm.apply(
            _env(EventType.SENSOR_READING, {"sensor_id": None})
        )
        # Engine survived; subsequent applies still work.
        await rm.apply(
            _env(
                EventType.SENSOR_READING,
                {
                    "sensor_id": "s-ok",
                    "sensor_type": "temperature",
                    "value": 20.0,
                    "unit": "celsius",
                    "recorded_at": "2026-05-11T08:00:00+00:00",
                },
            )
        )
        sensors = await rm.list_sensors()
        assert [s.sensor_id for s in sensors] == ["s-ok"]
    finally:
        await rm.close()


@pytest.mark.asyncio
async def test_unknown_event_type_is_noop(tmp_path: Path) -> None:
    rm = await _make_rm(tmp_path)
    try:
        # All defined event types are covered; pick HEARTBEAT with empty payload
        # to exercise the path where dispatch runs but yields no useful state.
        await rm.apply(_env(EventType.DEVICE_HEARTBEAT, {}))
        status = await rm.get_status()
        # Falls back to the empty-projection default.
        assert status.device_id in {"unknown", None, ""}
    finally:
        await rm.close()
