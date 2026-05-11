"""WeightBelowTargetRule — gap vs target growth curve + min-confidence gate."""

from __future__ import annotations

import pytest

from edge.alerts.rules.weight_below_target import WeightBelowTargetRule
from edge.domain.events import EventEnvelope, EventType


def _estimate(weight_g: float, age: int, breed: str = "ross_308", confidence: float = 0.8) -> EventEnvelope:
    return EventEnvelope(
        event_type=EventType.WEIGHT_ESTIMATE,
        payload={
            "event_id": "00000000-0000-0000-0000-000000000001",
            "device_id": "edge-1",
            "camera_id": "cam-1",
            "shed_id": "shed-1",
            "flock_id": "flock-A",
            "captured_at": "2026-05-11T12:00:00+00:00",
            "processed_at": "2026-05-11T12:00:00+00:00",
            "model_version": "x",
            "estimated_avg_weight_g": weight_g,
            "confidence": confidence,
            "bird_age_days": age,
            "breed": breed,
        },
    )


@pytest.mark.asyncio
async def test_no_alert_when_at_target() -> None:
    # Ross 308 day 28 target ≈ 1620g.
    rule = WeightBelowTargetRule(device_id="edge-1", threshold_pct=0.15)
    assert (await rule.on_event(_estimate(1620, 28))) == []


@pytest.mark.asyncio
async def test_no_alert_when_only_slightly_below() -> None:
    # 10% gap < 15% threshold.
    rule = WeightBelowTargetRule(device_id="edge-1", threshold_pct=0.15)
    assert (await rule.on_event(_estimate(1458, 28))) == []   # 10% below 1620


@pytest.mark.asyncio
async def test_alert_when_significantly_below() -> None:
    rule = WeightBelowTargetRule(device_id="edge-1", threshold_pct=0.15)
    alerts = await rule.on_event(_estimate(1200, 28))         # ~26% below 1620
    assert len(alerts) == 1
    assert alerts[0].alert_type.value == "weight_below_target"
    assert alerts[0].flock_id == "flock-A"
    assert alerts[0].metrics["target_g"] == pytest.approx(1620.0, abs=1.0)
    assert alerts[0].metrics["gap_pct"] > 0.15


@pytest.mark.asyncio
async def test_low_confidence_is_ignored() -> None:
    """Stub estimates report confidence 0.05 — they must not trigger alerts."""
    rule = WeightBelowTargetRule(device_id="edge-1", min_confidence=0.3)
    assert (await rule.on_event(_estimate(0, 28, confidence=0.05))) == []


@pytest.mark.asyncio
async def test_unknown_breed_falls_back_to_default() -> None:
    rule = WeightBelowTargetRule(device_id="edge-1", threshold_pct=0.15)
    # Unknown breed → use ross_308 curve. 1200 vs 1620 = ~26% gap → alert.
    alerts = await rule.on_event(_estimate(1200, 28, breed="dodo"))
    assert len(alerts) == 1


@pytest.mark.asyncio
async def test_missing_age_skips_rule() -> None:
    payload = _estimate(1000, 28).payload
    payload["bird_age_days"] = None
    ev = EventEnvelope(event_type=EventType.WEIGHT_ESTIMATE, payload=payload)
    rule = WeightBelowTargetRule(device_id="edge-1")
    assert (await rule.on_event(ev)) == []


@pytest.mark.asyncio
async def test_cooldown_suppresses_repeats() -> None:
    rule = WeightBelowTargetRule(
        device_id="edge-1", threshold_pct=0.15, cooldown_seconds=999.0
    )
    first = await rule.on_event(_estimate(1200, 28))
    second = await rule.on_event(_estimate(1100, 28))
    assert len(first) == 1
    assert len(second) == 0
