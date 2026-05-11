"""Shared helpers across rules (small, pure functions only)."""

from __future__ import annotations

from datetime import datetime


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        return None
