"""SensorSupervisor — reconciles sensor pipelines against EdgeConfig.sensors.

Sensors are grouped by `source.protocol`; one SensorPipeline runs per protocol
group (so all MQTT sensors share one connection, all Modbus sensors share one
poller). When the spec list for a protocol changes, that protocol's pipeline
restarts; other protocols keep running.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import anyio
import structlog

from edge.supervisors.camera_supervisor import Runnable

log = structlog.get_logger(__name__)


SensorPipelineFactory = Callable[[str, list[dict[str, Any]]], Runnable]


@dataclass(slots=True)
class _RunningGroup:
    scope: anyio.CancelScope
    sensors: list[dict[str, Any]]


class SensorSupervisor:
    def __init__(
        self,
        task_group: anyio.abc.TaskGroup,
        factory: SensorPipelineFactory,
    ) -> None:
        self._tg = task_group
        self._factory = factory
        self._running: dict[str, _RunningGroup] = {}
        self._lock = anyio.Lock()

    @property
    def running_protocols(self) -> list[str]:
        return list(self._running)

    async def apply(self, desired_sensors: list[dict[str, Any]]) -> None:
        """Idempotent reconcile against the latest sensor list."""
        async with self._lock:
            by_protocol = self._group_by_protocol(desired_sensors)

            # Stop removed or changed protocol groups.
            for protocol in list(self._running):
                running = self._running[protocol]
                if protocol not in by_protocol:
                    log.info("sensor.group.stop", protocol=protocol, reason="removed")
                    running.scope.cancel()
                    self._running.pop(protocol, None)
                elif by_protocol[protocol] != running.sensors:
                    log.info("sensor.group.restart", protocol=protocol, reason="config_changed")
                    running.scope.cancel()
                    self._running.pop(protocol, None)

            # Start new groups.
            for protocol, sensors in by_protocol.items():
                if protocol in self._running:
                    continue
                scope = anyio.CancelScope()
                self._running[protocol] = _RunningGroup(scope=scope, sensors=list(sensors))
                self._tg.start_soon(self._run_one, protocol, sensors, scope)
                log.info("sensor.group.start", protocol=protocol, sensors=len(sensors))

    async def shutdown(self) -> None:
        async with self._lock:
            for protocol, running in self._running.items():
                log.info("sensor.group.shutdown", protocol=protocol)
                running.scope.cancel()
            self._running.clear()

    # ── private ────────────────────────────────────────────────────────────
    @staticmethod
    def _group_by_protocol(
        sensors: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        by_protocol: dict[str, list[dict[str, Any]]] = {}
        for s in sensors:
            protocol = (s.get("source") or {}).get("protocol")
            if not protocol:
                log.warning("sensor.spec.no_protocol", sensor_id=s.get("sensor_id"))
                continue
            by_protocol.setdefault(str(protocol), []).append(s)
        return by_protocol

    async def _run_one(
        self,
        protocol: str,
        sensors: list[dict[str, Any]],
        scope: anyio.CancelScope,
    ) -> None:
        with scope:
            try:
                pipeline = self._factory(protocol, sensors)
                run = getattr(pipeline, "run", None)
                if run is None:
                    raise TypeError("factory must return an object with an async `run()` method")
                result = run()
                if isinstance(result, Awaitable):
                    await result
            except Exception as exc:  # noqa: BLE001
                log.exception(
                    "sensor.pipeline.crashed",
                    protocol=protocol,
                    error=str(exc),
                )
            finally:
                if (
                    self._running.get(protocol) is not None
                    and self._running[protocol].scope is scope
                ):
                    self._running.pop(protocol, None)
