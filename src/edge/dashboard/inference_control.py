"""Dashboard-facing layer over InferenceSupervisor.

Lists available versions per model name (by scanning `models/<name>/*`),
exposes a "select version" entry point, and persists the user's choice to
`state/inference_selection.json` so it survives restarts.

Why a separate module: the InferenceSupervisor is happy to hot-swap a
version when told to (`set_override`), but it has no awareness of:
  - what versions exist on disk
  - whether a given version's artifact is present
  - what the user has previously chosen across restarts

This module owns those concerns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
import structlog

from edge.inference.model_loader import ModelLoader
from edge.supervisors.inference_supervisor import InferenceSupervisor

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class VersionInfo:
    version: str
    algorithm: str            # dbscan | yolo-seg | density | heuristic | stub | …
    display_name: str         # friendly label for the dropdown
    requires_artifact: bool   # True for ML algorithms (yolo-seg, density)
    artifact_present: bool    # True iff the .pt / .onnx actually exists
    available: bool           # True iff the version can be selected today
    is_active: bool           # True iff this version is currently running
    notes: str | None = None  # surfaced to the UI when `available` is False


# Friendly labels for known algorithm tags.
_DISPLAY_NAMES: dict[str, str] = {
    # Huddling
    "dbscan": "DBSCAN — centroid clustering",
    "yolo-seg": "YOLOv8-seg — mask-overlap clustering",
    "density": "Density estimation — CSRNet-style heatmap",
    # Weight
    "heuristic": "Heuristic — breed/age growth curve",
    "bbox-area": "Bbox-area — linear regression",
    "mask-area": "Mask-area — YOLOv8-seg + linear regression",
    "cnn-regression": "CNN — per-bird image regression",
    # Generic
    "stub": "Stub (synthetic placeholder)",
}


class InferenceControl:
    """Per-model dropdown state for the dashboard."""

    def __init__(
        self,
        *,
        supervisor: InferenceSupervisor,
        loader: ModelLoader,
        models_root: Path,
        state_path: Path,
    ) -> None:
        self._supervisor = supervisor
        self._loader = loader
        self._models_root = models_root
        self._state_path = state_path
        self._lock = anyio.Lock()

    async def load(self) -> None:
        """Restore saved overrides from disk so user choices survive restart.

        Doesn't perform the actual swap — just registers the override with the
        InferenceSupervisor. ConfigPipeline's first `apply()` after boot is
        what triggers the install, with the override now in play.
        """
        if not self._state_path.is_file():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "inference_control.load.failed",
                path=str(self._state_path),
                error=str(exc),
            )
            return
        for name, version in (data.get("overrides") or {}).items():
            self._supervisor._overrides[str(name)] = str(version)  # type: ignore[attr-defined]
        log.info(
            "inference_control.loaded",
            overrides=self._supervisor.list_overrides(),
            path=str(self._state_path),
        )

    async def list_versions(self, model_name: str) -> list[VersionInfo]:
        """All discovered versions of a model, with availability + active flag."""

        def _scan() -> list[VersionInfo]:
            root = self._models_root / model_name
            if not root.is_dir():
                return []
            active = self._supervisor.current_version_for(model_name)
            out: list[VersionInfo] = []
            for sub in sorted(root.iterdir()):
                if not sub.is_dir():
                    continue
                if sub.name in {"latest"}:
                    continue
                info = self._inspect(model_name, sub, active)
                if info is not None:
                    out.append(info)
            return out

        return await anyio.to_thread.run_sync(_scan)

    async def select(self, model_name: str, version: str) -> VersionInfo:
        """Switch the model to `version`. Persists the selection.

        Raises FileNotFoundError if the version directory or its required
        artifact is missing. Raises RuntimeError if installation itself fails.
        """
        async with self._lock:
            # Validate by attempting to load the descriptor.
            descriptor = await anyio.to_thread.run_sync(
                self._loader.load, model_name, version
            )
            # If it's an ML algorithm, also confirm the artifact exists.
            algorithm = str(descriptor.metadata.get("algorithm", "")).lower()
            if algorithm in {"yolo-seg", "density"} and (
                descriptor.artifact_path is None or not descriptor.artifact_path.is_file()
            ):
                raise FileNotFoundError(
                    f"Selected version {version!r} for {model_name!r} declares "
                    f"algorithm={algorithm!r} but no model artifact is on disk. "
                    "Train and drop in a .pt before switching."
                )

            try:
                await self._supervisor.set_override(model_name, version)
            except Exception as exc:  # noqa: BLE001
                # Roll back the override if install failed — we don't want to
                # persist a broken selection.
                await self._supervisor.clear_override(model_name)
                raise RuntimeError(f"Failed to install {model_name}@{version}: {exc}") from exc

            await self._persist_locked()
            log.info("inference_control.select", model=model_name, version=version)

        versions = await self.list_versions(model_name)
        for v in versions:
            if v.version == version:
                return v
        # Should never happen — version we just loaded must exist
        raise RuntimeError(f"Selected version {version} disappeared after install")

    # ── internal ───────────────────────────────────────────────────────────

    def _inspect(
        self,
        model_name: str,
        sub: Path,
        active_version: str | None,
    ) -> VersionInfo | None:
        version = sub.name
        meta_path = sub / "metadata.json"
        metadata: dict[str, Any] = {}
        if meta_path.is_file():
            try:
                metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                log.debug(
                    "inference_control.metadata.malformed",
                    model=model_name,
                    version=version,
                    error=str(exc),
                )

        algorithm = str(metadata.get("algorithm", "")).lower() or "unknown"
        # Heuristic vs ML
        format_ = str(metadata.get("format", "")).lower()
        # Algorithms that load a torch artifact off disk:
        ml_algorithms = {"yolo-seg", "density", "cnn-regression", "mask-area"}
        requires_artifact = algorithm in ml_algorithms or (
            format_ not in {"config-only", "stub"}
        )

        # Special-case the known config-only families so labels are friendly.
        config_only_algos = {"dbscan", "heuristic", "bbox-area"}
        if format_ == "config-only" and algorithm in config_only_algos:
            requires_artifact = False

        if requires_artifact:
            artifact_name = str(metadata.get("artifact", "model.onnx"))
            artifact_present = (sub / artifact_name).is_file()
        else:
            artifact_present = True

        available = artifact_present  # only blocker today
        notes: str | None = None
        if not available:
            notes = (
                f"Required artifact missing — drop a trained model at "
                f"{sub / metadata.get('artifact', 'model.pt')}"
            )

        # Display name: prefer algorithm-keyed label, fall back to algorithm tag.
        display_name = _DISPLAY_NAMES.get(algorithm, algorithm or version)

        return VersionInfo(
            version=version,
            algorithm=algorithm,
            display_name=display_name,
            requires_artifact=requires_artifact,
            artifact_present=artifact_present,
            available=available,
            is_active=active_version == version,
            notes=notes,
        )

    async def _persist_locked(self) -> None:
        data = {"overrides": self._supervisor.list_overrides()}
        text = json.dumps(data, indent=2)
        tmp = self._state_path.with_suffix(self._state_path.suffix + ".tmp")

        def _write() -> None:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(self._state_path)

        await anyio.to_thread.run_sync(_write)
