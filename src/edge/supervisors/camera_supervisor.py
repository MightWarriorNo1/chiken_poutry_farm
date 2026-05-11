"""CameraSupervisor — reconciles running frame pipelines against desired config.

Kubernetes-style: `apply(desired)` is idempotent. Cameras present in `desired`
that aren't running get started. Running cameras absent from `desired` get
cancelled. Running cameras whose config changed get restarted.

`set_extras(extras)` lets non-cloud callers (e.g. the DemoManager) inject
ephemeral camera configs that survive across cloud-config reconciles.

`set_on_complete(callback)` registers a hook fired when a pipeline finishes
naturally (e.g. a non-looping demo video runs out). Crashes do not fire it.

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

# Fired with a camera_id when its pipeline finishes without raising.
CompletionCallback = Callable[[str], Awaitable[None]]


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
        self._last_cloud: list[dict[str, Any]] = []
        self._extras: list[dict[str, Any]] = []
        self._on_complete: CompletionCallback | None = None
        # Cameras whose pipelines completed naturally — they must not be
        # re-started until removed from extras (or apply() drops them).
        self._completed: set[str] = set()

    @property
    def running_cameras(self) -> list[str]:
        return list(self._running)

    def cameras_with_config(self) -> list[dict[str, Any]]:
        """Snapshot of every desired camera (running or just-completed) and its
        config. Used by the dashboard to surface type + status without exposing
        internal state."""
        merged = {c["camera_id"]: c for c in self._last_cloud + self._extras}
        return list(merged.values())

    def set_on_complete(self, callback: CompletionCallback | None) -> None:
        self._on_complete = callback

    async def apply(self, desired_cameras: list[dict[str, Any]]) -> None:
        """Idempotent reconcile with the cloud's view. Safe to call from a polling loop."""
        async with self._lock:
            self._last_cloud = list(desired_cameras)
            await self._reconcile_locked()

    async def set_extras(self, extras: list[dict[str, Any]]) -> None:
        """Set the ephemeral camera-config overlay (e.g. running demos).

        Idempotent — safe to call with the same value. Cameras in `extras`
        that previously completed naturally and are still in the new `extras`
        list are NOT restarted; remove them from `extras` before re-running.
        """
        async with self._lock:
            self._extras = list(extras)
            # When a caller removes a camera from extras, also let it run
            # again if a future set_extras call re-adds it.
            extra_ids = {c["camera_id"] for c in self._extras}
            self._completed = {c for c in self._completed if c in extra_ids}
            await self._reconcile_locked()

    async def shutdown(self) -> None:
        async with self._lock:
            for cam_id, running in self._running.items():
                log.info("camera.shutdown", camera_id=cam_id)
                running.scope.cancel()
            self._running.clear()

    # ── private ────────────────────────────────────────────────────────────

    async def _reconcile_locked(self) -> None:
        """Diff merged-desired against `_running`. Caller holds `_lock`."""
        merged = {c["camera_id"]: c for c in self._last_cloud + self._extras}

        # Stop removed or changed.
        for cam_id in list(self._running):
            running = self._running[cam_id]
            if cam_id not in merged:
                log.info("camera.stop", camera_id=cam_id, reason="removed")
                running.scope.cancel()
                self._running.pop(cam_id, None)
            elif merged[cam_id] != running.config:
                log.info("camera.restart", camera_id=cam_id, reason="config_changed")
                running.scope.cancel()
                self._running.pop(cam_id, None)
                # Treat a config-change as a fresh start — clear completed mark.
                self._completed.discard(cam_id)

        # Start new (but never restart something we already saw run to completion).
        for cam_id, cfg in merged.items():
            if cam_id in self._running:
                continue
            if cam_id in self._completed:
                continue
            scope = anyio.CancelScope()
            self._running[cam_id] = _Running(scope=scope, config=dict(cfg))
            self._tg.start_soon(self._run_one, cfg, scope)
            log.info("camera.start", camera_id=cam_id)

    async def _run_one(self, cfg: dict[str, Any], scope: anyio.CancelScope) -> None:
        cam_id = cfg["camera_id"]
        ended_naturally = False
        with scope:
            try:
                pipeline = self._factory(cfg)
                await self._await_pipeline(pipeline)
                ended_naturally = True
            except Exception as exc:  # noqa: BLE001
                log.exception("camera.pipeline.crashed", camera_id=cam_id, error=str(exc))
            finally:
                # Best-effort removal — apply() may have removed us already.
                if self._running.get(cam_id) is not None and self._running[cam_id].scope is scope:
                    self._running.pop(cam_id, None)
                if ended_naturally:
                    self._completed.add(cam_id)
                    if self._on_complete is not None:
                        try:
                            await self._on_complete(cam_id)
                        except Exception as exc:  # noqa: BLE001
                            log.exception(
                                "camera.on_complete.failed",
                                camera_id=cam_id,
                                error=str(exc),
                            )

    @staticmethod
    async def _await_pipeline(pipeline: object) -> None:
        run = getattr(pipeline, "run", None)
        if run is None:
            raise TypeError("factory must return an object with an async `run()` method")
        result = run()
        if isinstance(result, Awaitable):
            await result
