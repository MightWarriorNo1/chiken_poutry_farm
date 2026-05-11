"""HighHuddlingRule — consecutive-frame trigger + cooldown + recovery."""

from __future__ import annotations

import pytest

from edge.alerts.rules.high_huddling import HighHuddlingRule
from edge.domain.events import EventEnvelope, EventType


def _huddle(camera_id: str, score: float, zone_id: str | None = None) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.HUDDLING_SCORE,
        payload={
            "event_id": "00000000-0000-0000-0000-000000000001",
            "device_id": "edge-1",
            "camera_id": camera_id,
            "shed_id": "shed-1",
            "flock_id": "flock-A",
            "zone_id": zone_id,
            "captured_at": "2026-05-11T12:00:00+00:00",
            "processed_at": "2026-05-11T12:00:00+00:00",
            "model_version": "x",
            "huddling_score": score,
        },
    )


@pytest.mark.asyncio
async def test_single_high_score_no_alert() -> None:
    rule = HighHuddlingRule(device_id="edge-1", threshold=0.7, consecutive_frames=3)
    assert (await rule.on_event(_huddle("cam-1", 0.9))) == []


@pytest.mark.asyncio
async def test_alert_after_consecutive_threshold_breaches() -> None:
    rule = HighHuddlingRule(device_id="edge-1", threshold=0.7, consecutive_frames=3)
    assert (await rule.on_event(_huddle("cam-1", 0.8))) == []
    assert (await rule.on_event(_huddle("cam-1", 0.85))) == []
    alerts = await rule.on_event(_huddle("cam-1", 0.9))
    assert len(alerts) == 1
    assert alerts[0].alert_type.value == "high_huddling"
    assert alerts[0].camera_id == "cam-1"
    assert alerts[0].metrics["consecutive"] == 3
    assert alerts[0].correlation_key == "high_huddling:cam-1"


@pytest.mark.asyncio
async def test_below_threshold_resets_counter() -> None:
    rule = HighHuddlingRule(device_id="edge-1", threshold=0.7, consecutive_frames=3)
    await rule.on_event(_huddle("cam-1", 0.8))
    await rule.on_event(_huddle("cam-1", 0.85))
    # One dip → counter resets.
    await rule.on_event(_huddle("cam-1", 0.5))
    await rule.on_event(_huddle("cam-1", 0.8))
    await rule.on_event(_huddle("cam-1", 0.85))
    alerts = await rule.on_event(_huddle("cam-1", 0.9))
    assert len(alerts) == 1


@pytest.mark.asyncio
async def test_cooldown_suppresses_immediate_re_alert() -> None:
    rule = HighHuddlingRule(
        device_id="edge-1", threshold=0.7, consecutive_frames=2, cooldown_seconds=999.0
    )
    await rule.on_event(_huddle("cam-1", 0.8))
    first = await rule.on_event(_huddle("cam-1", 0.85))
    second = await rule.on_event(_huddle("cam-1", 0.9))
    assert len(first) == 1
    assert len(second) == 0


@pytest.mark.asyncio
async def test_per_camera_isolation() -> None:
    rule = HighHuddlingRule(device_id="edge-1", threshold=0.7, consecutive_frames=2)
    await rule.on_event(_huddle("cam-1", 0.8))
    fired_cam1 = await rule.on_event(_huddle("cam-1", 0.85))
    # cam-2's first high-score shouldn't fire (needs 2 consecutive).
    fired_cam2 = await rule.on_event(_huddle("cam-2", 0.95))
    assert len(fired_cam1) == 1
    assert len(fired_cam2) == 0
