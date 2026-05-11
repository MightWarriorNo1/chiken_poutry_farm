"""InferenceSupervisor — reconciles ALL inference models against EdgeConfig.ai.

Each model name (e.g. `bird-detector`, `weight-estimator`) is registered via a
`ModelHandler` describing how to build a new instance and install it into the
right registry. Adding a new model name is a one-line change in `main.py`; the
supervisor itself never needs to know what the models do.

Failed installs are logged but don't disturb the previously-installed model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import structlog

from edge.inference.model_loader import ModelDescriptor, ModelLoader

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ModelHandler:
    """How to build a model from a descriptor and install it into a registry."""

    build: Callable[[ModelDescriptor], Any]
    install: Callable[[Any], Any]  # returns previous instance for telemetry / cleanup


class InferenceSupervisor:
    def __init__(
        self,
        loader: ModelLoader,
        handlers: dict[str, ModelHandler],
    ) -> None:
        self._loader = loader
        self._handlers = handlers
        self._current: dict[str, str] = {}  # model_name → version

    def versions(self) -> dict[str, str]:
        """Snapshot of currently-installed model versions, keyed by model name."""
        return dict(self._current)

    def current_version_for(self, model_name: str) -> str | None:
        return self._current.get(model_name)

    async def apply(self, ai_config: dict[str, Any]) -> None:
        for entry in self._iter_model_entries(ai_config):
            name = entry["name"]
            version = entry["version"]
            if name not in self._handlers:
                continue  # unknown model name; not our job
            if self._current.get(name) == version:
                continue  # idempotent
            await self._install(name, version)

    # ── internal ───────────────────────────────────────────────────────────
    @staticmethod
    def _iter_model_entries(ai_config: dict[str, Any]):
        for entry in ai_config.get("models") or []:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            version = entry.get("version")
            if name and version:
                yield {"name": str(name), "version": str(version)}

    async def _install(self, name: str, version: str) -> None:
        try:
            descriptor = self._loader.load(name, version)
            handler = self._handlers[name]
            new_instance = handler.build(descriptor)
            start = getattr(new_instance, "start", None)
            if callable(start):
                await start()
            old = handler.install(new_instance)
            self._current[name] = version
            log.info(
                "inference.swap",
                model=name,
                from_=getattr(old, "model_version", None),
                to=descriptor.reference,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception(
                "inference.swap.failed",
                model=name,
                version=version,
                error=str(exc),
            )
