"""SensorSupervisor groups by protocol and reconciles per group."""

from __future__ import annotations

from typing import Any

import anyio
import pytest

from edge.supervisors.sensor_supervisor import SensorSupervisor


class _FakeGroupPipeline:
    started: list[tuple[str, int]] = []  # (protocol, sensor_count)
    stopped: list[str] = []

    def __init__(self, protocol: str, sensors: list[dict[str, Any]]) -> None:
        self._protocol = protocol
        self._sensors = sensors

    async def run(self) -> None:
        _FakeGroupPipeline.started.append((self._protocol, len(self._sensors)))
        try:
            await anyio.sleep_forever()
        finally:
            _FakeGroupPipeline.stopped.append(self._protocol)


@pytest.fixture(autouse=True)
def _reset() -> None:
    _FakeGroupPipeline.started.clear()
    _FakeGroupPipeline.stopped.clear()


def _spec(sensor_id: str, protocol: str, **extra: Any) -> dict[str, Any]:
    s = {
        "sensor_id": sensor_id,
        "sensor_type": "temperature",
        "source": {"protocol": protocol, **extra},
    }
    return s


@pytest.mark.asyncio
async def test_groups_sensors_by_protocol() -> None:
    async with anyio.create_task_group() as tg:
        sup = SensorSupervisor(task_group=tg, factory=_FakeGroupPipeline)
        await sup.apply([
            _spec("a", "mqtt", topic="p/a"),
            _spec("b", "mqtt", topic="p/b"),
            _spec("c", "simulator"),
        ])
        await anyio.sleep(0.05)
        # mqtt group has 2 sensors; simulator group has 1.
        assert sorted(sup.running_protocols) == ["mqtt", "simulator"]
        starts = sorted(_FakeGroupPipeline.started)
        assert starts == [("mqtt", 2), ("simulator", 1)]
        tg.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_stop_protocol_when_removed() -> None:
    async with anyio.create_task_group() as tg:
        sup = SensorSupervisor(task_group=tg, factory=_FakeGroupPipeline)
        await sup.apply([_spec("a", "mqtt", topic="p/a"), _spec("c", "simulator")])
        await anyio.sleep(0.05)

        await sup.apply([_spec("c", "simulator")])
        await anyio.sleep(0.05)
        assert "mqtt" in _FakeGroupPipeline.stopped
        assert sup.running_protocols == ["simulator"]
        tg.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_restart_protocol_when_sensors_change() -> None:
    async with anyio.create_task_group() as tg:
        sup = SensorSupervisor(task_group=tg, factory=_FakeGroupPipeline)
        await sup.apply([_spec("a", "mqtt", topic="p/a")])
        await anyio.sleep(0.05)
        await sup.apply([_spec("a", "mqtt", topic="p/a"), _spec("b", "mqtt", topic="p/b")])
        await anyio.sleep(0.05)
        # mqtt started twice (once with 1 sensor, once with 2), stopped at least once.
        starts = [s for s in _FakeGroupPipeline.started if s[0] == "mqtt"]
        assert starts == [("mqtt", 1), ("mqtt", 2)]
        assert _FakeGroupPipeline.stopped.count("mqtt") >= 1
        tg.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_idempotent_apply() -> None:
    async with anyio.create_task_group() as tg:
        sup = SensorSupervisor(task_group=tg, factory=_FakeGroupPipeline)
        cfg = [_spec("a", "mqtt", topic="p/a"), _spec("c", "simulator")]
        await sup.apply(cfg)
        await anyio.sleep(0.05)
        await sup.apply(cfg)
        await sup.apply(cfg)
        await anyio.sleep(0.05)
        assert _FakeGroupPipeline.started.count(("mqtt", 1)) == 1
        assert _FakeGroupPipeline.started.count(("simulator", 1)) == 1
        tg.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_skip_sensors_without_protocol() -> None:
    async with anyio.create_task_group() as tg:
        sup = SensorSupervisor(task_group=tg, factory=_FakeGroupPipeline)
        await sup.apply([{"sensor_id": "broken", "sensor_type": "temperature"}])
        await anyio.sleep(0.05)
        assert sup.running_protocols == []
        tg.cancel_scope.cancel()
