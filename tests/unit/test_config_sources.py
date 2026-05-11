"""YamlConfigSource: load, no-change detection, hot-reload on mtime."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from edge.config_sources.yaml_config_source import YamlConfigSource


@pytest.mark.asyncio
async def test_yaml_source_loads_then_returns_none_when_unchanged(tmp_path: Path) -> None:
    p = tmp_path / "edge.yaml"
    p.write_text(
        """
        device_id: edge-1
        cameras:
          - camera_id: cam-1
            source_uri: file://./x
            role: general
        """.strip(),
        encoding="utf-8",
    )
    src = YamlConfigSource(p)

    first = await src.fetch()
    assert first is not None
    assert first["device_id"] == "edge-1"
    assert len(first["cameras"]) == 1

    second = await src.fetch()
    assert second is None  # unchanged


@pytest.mark.asyncio
async def test_yaml_source_reloads_on_mtime_change(tmp_path: Path) -> None:
    p = tmp_path / "edge.yaml"
    p.write_text("cameras: []", encoding="utf-8")
    src = YamlConfigSource(p)

    assert (await src.fetch()) is not None
    assert (await src.fetch()) is None

    # Bump mtime forward — some filesystems have second-resolution mtime.
    future = time.time() + 2
    os.utime(p, (future, future))
    p.write_text("cameras:\n  - camera_id: c1\n    source_uri: file://./x\n    role: general", encoding="utf-8")

    reloaded = await src.fetch()
    assert reloaded is not None
    assert reloaded["cameras"][0]["camera_id"] == "c1"


@pytest.mark.asyncio
async def test_yaml_source_missing_file_returns_none(tmp_path: Path) -> None:
    src = YamlConfigSource(tmp_path / "does-not-exist.yaml")
    assert (await src.fetch()) is None
