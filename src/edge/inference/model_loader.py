"""Versioned AI model registry.

A `ModelDescriptor` is a pointer + metadata; loading the actual ONNX session is
the adapter's responsibility (lazy, expensive). This separation lets the
ConfigPipeline hand a descriptor to the InferenceSupervisor without paying for
inference setup until the descriptor is selected.

Filesystem layout (see [models/README.md](../../../models/README.md)):

    models/
      <name>/
        <version>/
          model.onnx
          metadata.json
          eval.md
        latest -> <version>     (optional symlink)

`stub-*` versions are virtual — no disk artifact required. Used by the
StubBirdDetector for offline demos.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    name: str
    version: str
    artifact_path: Path | None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def reference(self) -> str:
        """Canonical `<name>@<version>` — used as `model_version` on every event."""
        return f"{self.name}@{self.version}"

    @property
    def is_stub(self) -> bool:
        """True only when the version is explicitly tagged `stub-*`.

        Real adapters that don't need a disk artifact (heuristic / config-only
        models like the DBSCAN huddling detector) get `artifact_path=None` but
        are NOT stubs — their factory builds the heuristic adapter from the
        metadata dict.
        """
        return self.version.startswith("stub")


class ModelLoader:
    """Resolves `<root>/<name>/<version>/` into a ModelDescriptor."""

    def __init__(self, models_root: Path) -> None:
        self._root = Path(models_root)

    def load(self, name: str, version: str) -> ModelDescriptor:
        # Stub versions are virtual — no disk artifact required.
        if version.startswith("stub"):
            return ModelDescriptor(
                name=name,
                version=version,
                artifact_path=None,
                metadata={"name": name, "version": version, "framework": "stub"},
            )

        version_dir = self._root / name / version
        if not version_dir.is_dir():
            raise FileNotFoundError(
                f"Model directory not found: {version_dir}. "
                f"Run scripts/download_yolov8n.py to bootstrap, or check models/{name}/."
            )

        metadata_path = version_dir / "metadata.json"
        if not metadata_path.is_file():
            raise FileNotFoundError(f"Missing metadata.json in {version_dir}")

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        # Config-only models (heuristic adapters like the weight estimator +
        # DBSCAN huddling detector) carry no disk artifact — `format` says so
        # explicitly. They get a descriptor with no artifact_path; their
        # factory then constructs a pure-Python adapter from `metadata`.
        if metadata.get("format") == "config-only":
            return ModelDescriptor(
                name=name,
                version=version,
                artifact_path=None,
                metadata=metadata,
            )

        artifact_name = metadata.get("artifact", "model.onnx")
        artifact_path = version_dir / artifact_name
        if not artifact_path.is_file():
            raise FileNotFoundError(f"Missing artifact: {artifact_path}")

        return ModelDescriptor(
            name=name,
            version=version,
            artifact_path=artifact_path,
            metadata=metadata,
        )

    def latest(self, name: str) -> ModelDescriptor:
        """Resolve `<root>/<name>/latest`, or fall back to the lexically-highest version."""
        link = self._root / name / "latest"
        if link.exists():
            return self.load(name, link.resolve().name)

        name_root = self._root / name
        if not name_root.is_dir():
            raise FileNotFoundError(f"No versions for model: {name}")
        candidates = sorted(
            (p.name for p in name_root.iterdir() if p.is_dir() and p.name != "latest"),
            reverse=True,
        )
        if not candidates:
            raise FileNotFoundError(f"No versions for model: {name}")
        return self.load(name, candidates[0])
