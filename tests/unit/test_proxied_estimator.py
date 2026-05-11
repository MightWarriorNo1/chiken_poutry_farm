"""ProxiedWeightEstimator forwards to the current registry entry."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection
from edge.inference.models.stub_weight_estimator import StubWeightEstimator
from edge.inference.proxied_estimator import EstimatorRegistry, ProxiedWeightEstimator


def _frame() -> Frame:
    return Frame(
        camera_id="c",
        captured_at=datetime.now(timezone.utc),
        width=640,
        height=480,
        image=None,
    )


def _detection() -> BirdDetection:
    return BirdDetection(
        device_id="edge-1",
        camera_id="c",
        captured_at=datetime.now(timezone.utc),
        processed_at=datetime.now(timezone.utc),
        model_version="bird@x",
        bird_count=10,
        density_score=0.1,
        confidence=0.5,
    )


@pytest.mark.asyncio
async def test_proxy_delegates_to_current() -> None:
    a = StubWeightEstimator(model_version="weight-estimator@a", fixed_weight_g=1000)
    b = StubWeightEstimator(model_version="weight-estimator@b", fixed_weight_g=2000)
    registry = EstimatorRegistry(initial=a)
    proxy = ProxiedWeightEstimator(registry)

    first = await proxy.estimate(_frame(), _detection())
    assert first.model_version == "weight-estimator@a"
    assert first.estimated_avg_weight_g == 1000

    registry.swap(b)
    assert proxy.model_version == "weight-estimator@b"
    second = await proxy.estimate(_frame(), _detection())
    assert second.estimated_avg_weight_g == 2000
