"""ModelLoader: directory layout, latest resolution, error cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edge.inference.model_loader import ModelLoader


def _write_model(root: Path, name: str, version: str, with_metadata: bool = True) -> Path:
    d = root / name / version
    d.mkdir(parents=True, exist_ok=True)
    (d / "model.onnx").write_bytes(b"fake-onnx")
    if with_metadata:
        (d / "metadata.json").write_text(json.dumps({"version": version}))
    return d


def test_loads_explicit_version(tmp_path: Path) -> None:
    _write_model(tmp_path, "bird-detector", "v1.0.0")
    desc = ModelLoader(root=tmp_path).load("bird-detector", "v1.0.0")
    assert desc.version == "v1.0.0"
    assert desc.reference == "bird-detector@v1.0.0"
    assert desc.artifact_path.name == "model.onnx"
    assert desc.metadata["version"] == "v1.0.0"


def test_latest_resolves_to_highest_version(tmp_path: Path) -> None:
    _write_model(tmp_path, "bird-detector", "v1.0.0")
    _write_model(tmp_path, "bird-detector", "v1.2.0")
    _write_model(tmp_path, "bird-detector", "v1.1.0")
    desc = ModelLoader(root=tmp_path).load("bird-detector")
    assert desc.version == "v1.2.0"


def test_missing_artifact_raises(tmp_path: Path) -> None:
    d = tmp_path / "bird-detector" / "v1.0.0"
    d.mkdir(parents=True)
    # no model.onnx
    with pytest.raises(FileNotFoundError, match="No model artifact"):
        ModelLoader(root=tmp_path).load("bird-detector", "v1.0.0")


def test_missing_version_raises(tmp_path: Path) -> None:
    _write_model(tmp_path, "bird-detector", "v1.0.0")
    with pytest.raises(FileNotFoundError, match="Model not found"):
        ModelLoader(root=tmp_path).load("bird-detector", "v9.9.9")


def test_no_metadata_returns_empty_dict(tmp_path: Path) -> None:
    _write_model(tmp_path, "bird-detector", "v1.0.0", with_metadata=False)
    desc = ModelLoader(root=tmp_path).load("bird-detector", "v1.0.0")
    assert desc.metadata == {}
