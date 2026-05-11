"""InferenceSupervisor — reconciles loaded AI models against `EdgeConfig.ai.models`.

Implements the `BirdDetector` port itself (via delegation), so FramePipeline stays
agnostic about whether the underlying detector is the YOLO ONNX runtime, a stub,
or (later) a Triton client. `apply()` is idempotent and falls back to the stub if
loading a real model fails — the edge keeps running even when a model artifact is
missing or corrupt.

WeightEstimator and HuddlingDetector get the same treatment in Sprints 4 and 5.
"""

from __future__ import annotations

from typing import Any

import anyio
import structlog

from edge.capture.source import Frame
from edge.domain.detection import BirdDetection
from edge.inference.inference import BirdDetector
from edge.inference.model_loader import ModelLoader
from edge.inference.models.bird_detector import YoloBirdDetector
from edge.inference.models.stub_detector import StubBirdDetector

log = structlog.get_logger(__name__)


class InferenceSupervisor:
    """A BirdDetector facade that swaps its delegate on `apply()`.

    The delegate may be a `StubBirdDetector` (no model, deterministic fakes) or a
    `YoloBirdDetector` loaded from disk. Consumers (FramePipeline) hold a reference
    to the supervisor and call `detect()` per frame; the swap is invisible to them.
    """

    def __init__(self, model_loader: ModelLoader) -> None:
        self._loader = model_loader
        self._bird: BirdDetector = StubBirdDetector()
        self._lock = anyio.Lock()

    # ── BirdDetector port (delegation) ─────────────────────────────────────
    @property
    def model_version(self) -> str:
        return self._bird.model_version

    async def detect(self, frame: Frame) -> BirdDetection:
        # Read once, await — protects against mid-call swaps.
        active = self._bird
        return await active.detect(frame)

    # ── Reconciliation ─────────────────────────────────────────────────────
    async def apply(self, ai_config: dict[str, Any]) -> None:
        async with self._lock:
            models = ai_config.get("models") or []
            bird_cfg = next(
                (m for m in models if m.get("name") == "bird-detector"), None
            )
            await self._reconcile_bird(bird_cfg)

    async def _reconcile_bird(self, cfg: dict[str, Any] | None) -> None:
        if cfg is None:
            self._set_bird(StubBirdDetector(), reason="no_config")
            return

        version = str(cfg["version"])
        if self._bird.model_version.endswith(f"@{version}"):
            return  # already loaded

        if version.startswith("stub"):
            self._set_bird(
                StubBirdDetector(model_version=f"bird-detector@{version}"),
                reason="stub_version",
                version=version,
            )
            return

        try:
            descriptor = self._loader.load("bird-detector", version)
            detector = YoloBirdDetector(descriptor)
            await detector.start()
            self._set_bird(detector, reason="loaded", version=version)
        except Exception as exc:  # noqa: BLE001
            log.exception(
                "inference.bird.load_failed",
                version=version,
                error=str(exc),
            )
            self._set_bird(
                StubBirdDetector(model_version="bird-detector@stub-fallback"),
                reason="load_failed_fallback",
                version=version,
            )

    def _set_bird(self, detector: BirdDetector, **fields: Any) -> None:
        self._bird = detector
        log.info("inference.bird.active", model=detector.model_version, **fields)
