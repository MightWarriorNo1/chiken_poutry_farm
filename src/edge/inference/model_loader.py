"""Versioned local model registry.

Models live under `models/<name>/<version>/` with a `metadata.json` describing the
runtime contract (input shape, classes, etc.). The loader does not touch the network;
remote model rollout happens by syncing files into `models/` then bumping config.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    name: str
    version: str
    artifact_path: Path
    metadata: dict[str, Any]

    @property
    def reference(self) -> str:
        """Stable, human-readable identifier for events: e.g. `bird-detector@v1.0.0`."""
        return f"{self.name}@{self.version}"


class ModelLoader:
    """Resolves `<name>` (latest symlink) or `<name>@<version>` to disk paths."""

    def __init__(self, root: Path = Path("models")) -> None:
        self._root = root

    _ARTIFACT_CANDIDATES = ("model.onnx", "model.pt")

    def load(self, name: str, version: str | None = None) -> ModelDescriptor:
        if version is None or version == "latest":
            target = self._resolve_latest(name)
        else:
            target = self._root / name / version

        if target is None or not target.exists():
            raise FileNotFoundError(
                f"Model not found: {name}@{version or 'latest'} (looked in {self._root / name})"
            )

        # `latest` may be a symlink — resolve for stable version tracking.
        resolved = target.resolve()
        meta_path = resolved / "metadata.json"
        metadata: dict[str, object] = {}
        if meta_path.exists():
            with meta_path.open("r", encoding="utf-8") as f:
                metadata = json.load(f)

        artifact = next(
            (resolved / fname for fname in self._ARTIFACT_CANDIDATES if (resolved / fname).exists()),
            None,
        )
        if artifact is None:
            raise FileNotFoundError(
                f"No model artifact in {resolved} "
                f"(looked for {self._ARTIFACT_CANDIDATES})"
            )

        actual_version = version if (version and version != "latest") else resolved.name
        return ModelDescriptor(
            name=name,
            version=actual_version,
            artifact_path=artifact,
            metadata=metadata,
        )

    def _resolve_latest(self, name: str) -> Path | None:
        """Prefer an explicit `latest` symlink; otherwise return the highest
        lexicographically-sorted version directory. Good enough for semver dirs."""
        base = self._root / name
        if not base.is_dir():
            return None
        latest = base / "latest"
        if latest.exists():
            return latest
        versions = sorted(
            (d for d in base.iterdir() if d.is_dir()),
            key=lambda d: d.name,
        )
        return versions[-1] if versions else None
