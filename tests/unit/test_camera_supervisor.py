"""CameraSupervisor reconciles desired vs running cameras."""

from __future__ import annotations

from typing import Any

import anyio
import pytest

from edge.supervisors.camera_supervisor import CameraSupervisor


class _FakePipeline:
    """Minimal pipeline that records its lifecycle."""

    started: list[str] = []
    stopped: list[str] = []

    def __init__(self, cfg: dict[str, Any]) -> None:
        self._cfg = cfg

    async def run(self) -> None:
        cam_id = self._cfg["camera_id"]
        _FakePipeline.started.append(cam_id)
        try:
            await anyio.sleep_forever()
        finally:
            _FakePipeline.stopped.append(cam_id)


@pytest.fixture(autouse=True)
def _reset_pipeline_state() -> None:
    _FakePipeline.started.clear()
    _FakePipeline.stopped.clear()


@pytest.mark.asyncio
async def test_apply_starts_new_cameras() -> None:
    async with anyio.create_task_group() as tg:
        sup = CameraSupervisor(task_group=tg, factory=_FakePipeline)
        await sup.apply([{"camera_id": "a"}, {"camera_id": "b"}])
        await anyio.sleep(0.05)
        assert sorted(sup.running_cameras) == ["a", "b"]
        assert sorted(_FakePipeline.started) == ["a", "b"]
        tg.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_apply_stops_removed_cameras() -> None:
    async with anyio.create_task_group() as tg:
        sup = CameraSupervisor(task_group=tg, factory=_FakePipeline)
        await sup.apply([{"camera_id": "a"}, {"camera_id": "b"}])
        await anyio.sleep(0.05)
        await sup.apply([{"camera_id": "b"}])
        await anyio.sleep(0.05)
        assert sup.running_cameras == ["b"]
        assert "a" in _FakePipeline.stopped
        tg.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_apply_restarts_changed_camera() -> None:
    async with anyio.create_task_group() as tg:
        sup = CameraSupervisor(task_group=tg, factory=_FakePipeline)
        await sup.apply([{"camera_id": "a", "source_uri": "rtsp://1"}])
        await anyio.sleep(0.05)
        await sup.apply([{"camera_id": "a", "source_uri": "rtsp://2"}])
        await anyio.sleep(0.05)
        # Started twice (initial + restart), stopped once so far.
        assert _FakePipeline.started.count("a") == 2
        assert _FakePipeline.stopped.count("a") >= 1
        tg.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_apply_is_idempotent() -> None:
    async with anyio.create_task_group() as tg:
        sup = CameraSupervisor(task_group=tg, factory=_FakePipeline)
        cfg = [{"camera_id": "a"}, {"camera_id": "b"}]
        await sup.apply(cfg)
        await anyio.sleep(0.05)
        await sup.apply(cfg)
        await sup.apply(cfg)
        await anyio.sleep(0.05)
        assert _FakePipeline.started.count("a") == 1
        assert _FakePipeline.started.count("b") == 1
        tg.cancel_scope.cancel()
