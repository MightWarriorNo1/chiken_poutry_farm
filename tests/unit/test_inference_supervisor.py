"""InferenceSupervisor: hot-swap on config change, no-op on unchanged, safe on errors."""

from __future__ import annotations

from pathlib import Path

import pytest

from edge.inference.model_loader import ModelLoader
from edge.inference.models.stub_detector import StubBirdDetector
from edge.inference.proxied_detector import DetectorRegistry
from edge.supervisors.inference_supervisor import InferenceSupervisor


def _fresh(tmp_path: Path) -> tuple[DetectorRegistry, InferenceSupervisor, StubBirdDetector]:
    initial = StubBirdDetector(model_version="bird-detector@stub-0.0.1")
    registry = DetectorRegistry(initial=initial)
    sup = InferenceSupervisor(registry, ModelLoader(tmp_path))
    return registry, sup, initial


@pytest.mark.asyncio
async def test_supervisor_swaps_to_new_stub_version(tmp_path: Path) -> None:
    registry, sup, initial = _fresh(tmp_path)
    await sup.apply({"models": [{"name": "bird-detector", "version": "stub-0.0.2"}]})

    assert registry.current is not initial
    assert registry.current.model_version == "bird-detector@stub-0.0.2"
    assert sup.current_version == "stub-0.0.2"


@pytest.mark.asyncio
async def test_supervisor_is_idempotent_when_version_unchanged(tmp_path: Path) -> None:
    registry, sup, _ = _fresh(tmp_path)

    await sup.apply({"models": [{"name": "bird-detector", "version": "stub-0.0.1"}]})
    first_after = registry.current

    await sup.apply({"models": [{"name": "bird-detector", "version": "stub-0.0.1"}]})
    assert registry.current is first_after  # no-op


@pytest.mark.asyncio
async def test_supervisor_ignores_unrelated_models(tmp_path: Path) -> None:
    registry, sup, initial = _fresh(tmp_path)

    await sup.apply({"models": []})
    assert registry.current is initial

    await sup.apply({"models": [{"name": "weight-estimator", "version": "1.0.0"}]})
    assert registry.current is initial


@pytest.mark.asyncio
async def test_supervisor_swap_failure_keeps_current(tmp_path: Path) -> None:
    registry, sup, initial = _fresh(tmp_path)
    # Real version that doesn't exist on disk → ModelLoader raises → swap rolled back.
    await sup.apply({"models": [{"name": "bird-detector", "version": "9.9.9"}]})
    assert registry.current is initial
    assert sup.current_version is None
