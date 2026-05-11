"""CameraSupervisor — reconciles running frame pipelines against desired config.

Kubernetes-style: `apply(desired)` is idempotent. Cameras present in `desired`
that aren't running get started. Running cameras absent from `desired` get
cancelled. Running cameras whose config changed get restarted.

The supervisor doesn't own the task group — `main.py` does — so all child tasks
participate in structured concurrency and one error tears the whole edge down
predictably.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import anyio
import structlog

log = structlog.get_logger(__name__)


class Runnable(Protocol):
    """Structural protocol every camera pipeline must satisfy."""

    async def run(self) -> None: ...


# A factory builds (and runs) one camera's pipeline from its config dict.
PipelineFactory = Callable[[dict[str, Any]], Runnable]


@dataclass(slots=True)
class _Running:
    scope: anyio.CancelScope
    config: dict[str, Any]


class CameraSupervisor:
    def __init__(self, task_group: anyio.abc.TaskGroup, factory: PipelineFactory) -> None:
        self._tg = task_group
        self._factory = factory
        self._running: dict[str, _Running] = {}
        self._lock = anyio.Lock()  # serialize reconciliations

    @property
    def running_cameras(self) -> list[str]:
        return list(self._running)

    async def apply(self, desired_cameras: list[dict[str, Any]]) -> None:
        """Idempotent reconcile. Safe to call from a polling loop."""
        async with self._lock:
            desired_by_id = {c["camera_id"]: c for c in desired_cameras}

            # Stop removed or changed.
            for cam_id in list(self._running):
                running = self._running[cam_id]
                if cam_id not in desired_by_id:
                    log.info("camera.stop", camera_id=cam_id, reason="removed")
                    running.scope.cancel()
                    self._running.pop(cam_id, None)
                elif desired_by_id[cam_id] != running.config:
                    log.info("camera.restart", camera_id=cam_id, reason="config_changed")
                    running.scope.cancel()
                    self._running.pop(cam_id, None)

            # Start new.
            for cam_id, cfg in desired_by_id.items():
                if cam_id in self._running:
                    continue
                scope = anyio.CancelScope()
                self._running[cam_id] = _Running(scope=scope, config=dict(cfg))
                self._tg.start_soon(self._run_one, cfg, scope)
                log.info("camera.start", camera_id=cam_id)

    async def shutdown(self) -> None:
        async with self._lock:
            for cam_id, running in self._running.items():
                log.info("camera.shutdown", camera_id=cam_id)
                running.scope.cancel()
            self._running.clear()

    # ── private ────────────────────────────────────────────────────────────
    async def _run_one(self, cfg: dict[str, Any], scope: anyio.CancelScope) -> None:
        cam_id = cfg["camera_id"]
        with scope:
            try:
                pipeline = self._factory(cfg)
                await self._await_pipeline(pipeline)
            except Exception as exc:  # noqa: BLE001
                log.exception("camera.pipeline.crashed", camera_id=cam_id, error=str(exc))
            finally:
                # Best-effort removal — apply() may have removed us already.
                if self._running.get(cam_id) is not None and self._running[cam_id].scope is scope:
                    self._running.pop(cam_id, None)

    @staticmethod
    async def _await_pipeline(pipeline: object) -> None:
        run = getattr(pipeline, "run", None)
        if run is None:
            raise TypeError("factory must return an object with an async `run()` method")
        result = run()
        if isinstance(result, Awaitable):
            await result
