"""Versioned local model registry.

Models live under `models/<name>/<version>/` with a `metadata.json` describing the
runtime contract (input shape, classes, etc.). The loader does not touch the network;
remote model rollout happens by syncing files into `models/` then bumping config.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    name: str
    version: str
    artifact_path: Path
    metadata: dict[str, object]

    @property
    def reference(self) -> str:
        """Stable, human-readable identifier for events: e.g. `bird-detector@1.0.0`."""
        return f"{self.name}@{self.version}"


class ModelLoader:
    """Resolves `<name>` (latest symlink) or `<name>@<version>` to disk paths."""

    def __init__(self, root: Path = Path("models")) -> None:
        self._root = root

    def load(self, name: str, version: str | None = None) -> ModelDescriptor:
        target = self._root / name / (version or "latest")
        if not target.exists():
            raise FileNotFoundError(f"Model not found: {name}@{version or 'latest'} ({target})")

        # `latest` is a symlink — resolve it for stable version tracking.
        resolved = target.resolve()
        meta_path = resolved / "metadata.json"
        metadata: dict[str, object] = {}
        if meta_path.exists():
            with meta_path.open("r", encoding="utf-8") as f:
                metadata = json.load(f)

        actual_version = version or resolved.name
        artifact = next(
            (resolved / fname for fname in ("model.onnx", "model.pt") if (resolved / fname).exists()),
            resolved,
        )
        return ModelDescriptor(
            name=name,
            version=actual_version,
            artifact_path=artifact,
            metadata=metadata,
        )
