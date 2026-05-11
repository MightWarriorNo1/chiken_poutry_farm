"""InferenceSupervisor: stub fallback, version pinning, hot-swap, load failure."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from edge.capture.source import Frame
from edge.inference.model_loader import ModelLoader
from edge.supervisors.inference_supervisor import InferenceSupervisor


def _frame() -> Frame:
    return Frame(
        camera_id="cam-1",
        captured_at=datetime.now(timezone.utc),
        width=640,
        height=480,
        image=None,
    )


@pytest.mark.asyncio
async def test_defaults_to_stub_before_apply(tmp_path: Path) -> None:
    sup = InferenceSupervisor(model_loader=ModelLoader(root=tmp_path))
    assert "stub" in sup.model_version.lower()
    # Can still detect immediately — stub doesn't need a model file.
    result = await sup.detect(_frame())
    assert result.bird_count >= 0


@pytest.mark.asyncio
async def test_apply_stub_version_keeps_stub(tmp_path: Path) -> None:
    sup = InferenceSupervisor(model_loader=ModelLoader(root=tmp_path))
    await sup.apply({"models": [{"name": "bird-detector", "version": "stub-0.0.1"}]})
    assert sup.model_version == "bird-detector@stub-0.0.1"


@pytest.mark.asyncio
async def test_apply_missing_model_falls_back_to_stub(tmp_path: Path) -> None:
    sup = InferenceSupervisor(model_loader=ModelLoader(root=tmp_path))
    await sup.apply({"models": [{"name": "bird-detector", "version": "v9.9.9"}]})
    # Loader couldn't find v9.9.9 → fall back to stub. Edge keeps running.
    assert "stub" in sup.model_version.lower()


@pytest.mark.asyncio
async def test_apply_no_bird_model_falls_back_to_stub(tmp_path: Path) -> None:
    sup = InferenceSupervisor(model_loader=ModelLoader(root=tmp_path))
    await sup.apply({"models": []})
    assert "stub" in sup.model_version.lower()


@pytest.mark.asyncio
async def test_apply_is_idempotent_for_same_version(tmp_path: Path) -> None:
    sup = InferenceSupervisor(model_loader=ModelLoader(root=tmp_path))
    await sup.apply({"models": [{"name": "bird-detector", "version": "stub-0.0.1"}]})
    first_id = id(sup._bird)  # noqa: SLF001 — white-box check
    await sup.apply({"models": [{"name": "bird-detector", "version": "stub-0.0.1"}]})
    assert id(sup._bird) == first_id  # noqa: SLF001
