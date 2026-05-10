"""Shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from edge.config import Settings


@pytest.fixture()
def tmp_outbox(tmp_path: Path) -> Path:
    return tmp_path / "outbox.db"


@pytest.fixture()
def settings(tmp_outbox: Path) -> Settings:
    s = Settings()
    s.storage.outbox_path = tmp_outbox
    s.telemetry.otel_exporter = "none"
    return s
