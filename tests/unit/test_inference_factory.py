"""build_bird_detector picks the right adapter; ProxiedBirdDetector follows registry swaps."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from edge.capture.source import Frame
from edge.inference.factory import build_bird_detector
from edge.inference.model_loader import ModelDescriptor
from edge.inference.models.stub_detector import StubBirdDetector
from edge.inference.proxied_detector import DetectorRegistry, ProxiedBirdDetector


def test_stub_descriptor_returns_stub() -> None:
    desc = ModelDescriptor(name="bird-detector", version="stub-0.0.1", artifact_path=None)
    detector = build_bird_detector(desc)
    assert isinstance(detector, StubBirdDetector)
    assert detector.model_version == "bird-detector@stub-0.0.1"


def test_real_descriptor_returns_yolo(tmp_path: Path) -> None:
    # We don't actually load the ONNX session — just verify type dispatch.
    fake_artifact = tmp_path / "model.onnx"
    fake_artifact.write_bytes(b"")
    desc = ModelDescriptor(
        name="bird-detector",
        version="1.0.0",
        artifact_path=fake_artifact,
        metadata={"input": {"shape": [1, 3, 640, 640]}},
    )
    from edge.inference.models.bird_detector import YoloBirdDetector

    detector = build_bird_detector(desc)
    assert isinstance(detector, YoloBirdDetector)


@pytest.mark.asyncio
async def test_proxy_delegates_to_current_registry_entry() -> None:
    a = StubBirdDetector(model_version="bird-detector@a", seed=1)
    b = StubBirdDetector(model_version="bird-detector@b", seed=1)
    registry = DetectorRegistry(initial=a)
    proxy = ProxiedBirdDetector(registry)

    frame = Frame(
        camera_id="c",
        captured_at=datetime.now(timezone.utc),
        width=640,
        height=480,
        image=None,
    )

    first = await proxy.detect(frame)
    assert first.model_version == "bird-detector@a"
    assert proxy.model_version == "bird-detector@a"

    registry.swap(b)
    second = await proxy.detect(frame)
    assert second.model_version == "bird-detector@b"
    assert proxy.model_version == "bird-detector@b"
