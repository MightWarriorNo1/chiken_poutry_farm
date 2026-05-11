"""CameraOfflineRule — last-seen tracking + threshold trigger + cooldown."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from edge.alerts.rules.camera_offline import CameraOfflineRule
from edge.domain.events import EventEnvelope, EventType


def _frame_event(camera_id: str, captured_at: datetime, shed_id: str = "shed-1") -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.BIRD_DETECTION,
        payload={
            "event_id": "00000000-0000-0000-0000-000000000001",
            "device_id": "edge-1",
            "camera_id": camera_id,
            "shed_id": shed_id,
            "captured_at": captured_at.isoformat(),
            "processed_at": captured_at.isoformat(),
            "model_version": "x",
            "bird_count": 1,
            "density_score": 0.1,
            "confidence": 0.9,
        },
    )


@pytest.mark.asyncio
async def test_no_alert_before_threshold() -> None:
    rule = CameraOfflineRule(device_id="edge-1", threshold_seconds=60.0)
    t0 = datetime.now(timezone.utc)
    await rule.on_event(_frame_event("cam-1", t0))
    alerts = await rule.tick(t0 + timedelta(seconds=30))
    assert alerts == []


@pytest.mark.asyncio
async def test_alert_when_threshold_exceeded() -> None:
    rule = CameraOfflineRule(device_id="edge-1", threshold_seconds=60.0)
    t0 = datetime.now(timezone.utc)
    await rule.on_event(_frame_event("cam-1", t0))
    alerts = await rule.tick(t0 + timedelta(seconds=90))
    assert len(alerts) == 1
    assert alerts[0].alert_type.value == "camera_offline"
    assert alerts[0].camera_id == "cam-1"
    assert alerts[0].shed_id == "shed-1"
    assert alerts[0].correlation_key == "camera_offline:cam-1"
    assert alerts[0].metrics["elapsed_seconds"] >= 60


@pytest.mark.asyncio
async def test_cooldown_suppresses_repeats() -> None:
    rule = CameraOfflineRule(
        device_id="edge-1", threshold_seconds=60.0, cooldown_seconds=300.0
    )
    t0 = datetime.now(timezone.utc)
    await rule.on_event(_frame_event("cam-1", t0))

    first = await rule.tick(t0 + timedelta(seconds=90))
    second = await rule.tick(t0 + timedelta(seconds=120))
    third = await rule.tick(t0 + timedelta(seconds=400))   # after cooldown
    assert len(first) == 1
    assert len(second) == 0
    assert len(third) == 1


@pytest.mark.asyncio
async def test_new_frame_clears_cooldown() -> None:
    """Camera recovers, then goes offline again — should re-alert immediately."""
    rule = CameraOfflineRule(device_id="edge-1", threshold_seconds=60.0)
    t0 = datetime.now(timezone.utc)
    await rule.on_event(_frame_event("cam-1", t0))

    fired = await rule.tick(t0 + timedelta(seconds=90))
    assert len(fired) == 1

    # Camera comes back.
    await rule.on_event(_frame_event("cam-1", t0 + timedelta(seconds=100)))

    # Goes offline again → should re-alert without waiting for cooldown.
    again = await rule.tick(t0 + timedelta(seconds=200))
    assert len(again) == 1


@pytest.mark.asyncio
async def test_multiple_cameras_tracked_independently() -> None:
    rule = CameraOfflineRule(device_id="edge-1", threshold_seconds=60.0)
    t0 = datetime.now(timezone.utc)
    await rule.on_event(_frame_event("cam-1", t0))
    await rule.on_event(_frame_event("cam-2", t0 + timedelta(seconds=80)))
    alerts = await rule.tick(t0 + timedelta(seconds=90))
    # cam-1 last seen at t0 → 90s elapsed → alert.
    # cam-2 last seen at t0+80 → 10s elapsed → no alert.
    assert len(alerts) == 1
    assert alerts[0].camera_id == "cam-1"
