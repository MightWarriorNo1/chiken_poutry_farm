"""ModelLoader: descriptor construction + filesystem layout."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edge.inference.model_loader import ModelDescriptor, ModelLoader


def test_load_stub_version_no_disk_required(tmp_path: Path) -> None:
    loader = ModelLoader(tmp_path)
    desc = loader.load("bird-detector", "stub-0.0.1")
    assert desc.is_stub
    assert desc.artifact_path is None
    assert desc.reference == "bird-detector@stub-0.0.1"


def test_load_real_version_reads_metadata_and_artifact(tmp_path: Path) -> None:
    version_dir = tmp_path / "bird-detector" / "1.0.0"
    version_dir.mkdir(parents=True)
    (version_dir / "model.onnx").write_bytes(b"fake-onnx")
    (version_dir / "metadata.json").write_text(
        json.dumps(
            {
                "name": "bird-detector",
                "version": "1.0.0",
                "input": {"shape": [1, 3, 640, 640]},
                "thresholds": {"confidence": 0.3, "iou": 0.5},
            }
        ),
        encoding="utf-8",
    )

    desc = ModelLoader(tmp_path).load("bird-detector", "1.0.0")
    assert not desc.is_stub
    assert desc.artifact_path == version_dir / "model.onnx"
    assert desc.metadata["thresholds"]["confidence"] == 0.3
    assert desc.reference == "bird-detector@1.0.0"


def test_load_missing_metadata_raises(tmp_path: Path) -> None:
    (tmp_path / "bird-detector" / "1.0.0").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="metadata.json"):
        ModelLoader(tmp_path).load("bird-detector", "1.0.0")


def test_load_missing_artifact_raises(tmp_path: Path) -> None:
    version_dir = tmp_path / "bird-detector" / "1.0.0"
    version_dir.mkdir(parents=True)
    (version_dir / "metadata.json").write_text(
        json.dumps(
            {"name": "bird-detector", "version": "1.0.0", "artifact": "model.onnx"}
        ),
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError, match="artifact"):
        ModelLoader(tmp_path).load("bird-detector", "1.0.0")


def test_load_nonexistent_version_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Model directory not found"):
        ModelLoader(tmp_path).load("bird-detector", "9.9.9")


def test_descriptor_reference() -> None:
    d = ModelDescriptor(name="x", version="1.2.3", artifact_path=None)
    assert d.reference == "x@1.2.3"
    assert d.is_stub  # no artifact == stub
