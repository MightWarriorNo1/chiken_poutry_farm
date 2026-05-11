"""ProxiedHuddlingDetector forwards to the current registry entry."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection
from edge.inference.models.stub_huddling import StubHuddlingDetector
from edge.inference.proxied_huddling import HuddlingRegistry, ProxiedHuddlingDetector


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
    a = StubHuddlingDetector(model_version="huddling-detector@a")
    b = StubHuddlingDetector(model_version="huddling-detector@b")
    registry = HuddlingRegistry(initial=a)
    proxy = ProxiedHuddlingDetector(registry)

    first = await proxy.score(_frame(), _detection())
    assert first.model_version == "huddling-detector@a"

    registry.swap(b)
    assert proxy.model_version == "huddling-detector@b"
    second = await proxy.score(_frame(), _detection())
    assert second.model_version == "huddling-detector@b"
