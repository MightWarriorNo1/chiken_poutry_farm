"""InferenceSupervisor — reconciles the active detector against EdgeConfig.ai.

Mirrors the CameraSupervisor pattern: `apply(ai_config)` is idempotent; only
swaps when the requested version actually changes; failed swaps are logged but
preserve the current detector (so the pipeline doesn't fall over on a bad model
promotion).
"""

from __future__ import annotations

from typing import Any

import structlog

from edge.inference.factory import build_bird_detector
from edge.inference.model_loader import ModelLoader
from edge.inference.proxied_detector import DetectorRegistry

log = structlog.get_logger(__name__)

_BIRD_MODEL = "bird-detector"


class InferenceSupervisor:
    def __init__(self, registry: DetectorRegistry, loader: ModelLoader) -> None:
        self._registry = registry
        self._loader = loader
        self._current_version: str | None = None

    @property
    def current_version(self) -> str | None:
        return self._current_version

    async def apply(self, ai_config: dict[str, Any]) -> None:
        bird = self._extract_bird_entry(ai_config)
        if bird is None:
            return  # no instruction; leave current detector in place
        version = bird.get("version")
        if not version or version == self._current_version:
            return

        try:
            descriptor = self._loader.load(_BIRD_MODEL, version)
            new_detector = build_bird_detector(descriptor)
            start = getattr(new_detector, "start", None)
            if callable(start):
                await start()
            old = self._registry.swap(new_detector)
            self._current_version = version
            log.info(
                "inference.swap",
                from_=getattr(old, "model_version", None),
                to=descriptor.reference,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception(
                "inference.swap.failed",
                version=version,
                error=str(exc),
            )

    @staticmethod
    def _extract_bird_entry(ai_config: dict[str, Any]) -> dict[str, Any] | None:
        models = ai_config.get("models") or []
        for entry in models:
            if isinstance(entry, dict) and entry.get("name") == _BIRD_MODEL:
                return entry
        return None
