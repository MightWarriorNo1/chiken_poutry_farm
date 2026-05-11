"""File-based config source for offline development.

Loads an EdgeConfig from disk. Detects file changes via mtime so editing the file
hot-reloads cameras and sensors — handy during demos.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
import yaml

log = structlog.get_logger(__name__)


class YamlConfigSource:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._last_mtime: float = -1.0

    async def fetch(self) -> dict[str, Any] | None:
        if not self._path.is_file():
            log.warning("config.yaml.missing", path=str(self._path))
            return None

        mtime = self._path.stat().st_mtime
        if mtime == self._last_mtime:
            return None  # unchanged

        self._last_mtime = mtime
        with self._path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        log.info("config.yaml.loaded", path=str(self._path), mtime=mtime)
        return data
