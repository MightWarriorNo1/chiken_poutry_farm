"""Demo run history — persists past runs to a JSON file for the dashboard.

A "run" is one Start → (Stop | natural completion) cycle. Stats per run
(frame count, average / max bird count) are computed from `demo_outbox.db`
at end-of-run time, so we never have to maintain counters in the hot path.

File layout: `state/demo_history.json` — a list of `DemoRun` records, most
recent first, capped at `max_entries`. Written atomically via a `.tmp`
rename so a crash mid-write can't corrupt the file.

Runs interrupted by a process restart (started but never ended) survive in
the file with `ended_at=None` — the UI surfaces these as "incomplete."
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiosqlite
import anyio
import structlog

log = structlog.get_logger(__name__)

DEFAULT_MAX_ENTRIES = 200


@dataclass(slots=True)
class DemoRun:
    """One row in the demo-run history."""

    id: str
    kind: str                         # "video" | "image"
    name: str                         # bare filename
    started_at: str                   # ISO 8601 UTC
    ended_at: str | None = None
    ended_reason: str | None = None   # "stopped" | "completed" | None (in-progress / abandoned)
    frame_count: int | None = None
    bird_count_avg: float | None = None
    bird_count_max: int | None = None


class DemoHistoryStore:
    """JSON-backed log of past demo runs, with end-of-run stats from SQLite."""

    def __init__(
        self,
        *,
        path: Path,
        demo_outbox_path: Path,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._path = path
        self._outbox_path = demo_outbox_path
        self._max_entries = max_entries
        self._lock = anyio.Lock()
        self._runs: list[DemoRun] = []

    async def load(self) -> None:
        """Read the existing history file (if any). Safe to call at boot."""
        if not self._path.is_file():
            return
        try:
            raw = await anyio.to_thread.run_sync(self._path.read_text)
            data = json.loads(raw)
            self._runs = [DemoRun(**r) for r in data]
            log.info("demo_history.loaded", count=len(self._runs), path=str(self._path))
        except Exception as exc:  # noqa: BLE001
            log.warning("demo_history.load.failed", path=str(self._path), error=str(exc))
            self._runs = []

    async def begin_run(
        self,
        *,
        kind: str,
        name: str,
        started_at: datetime,
    ) -> str:
        """Append a new in-progress run. Returns the generated run id."""
        run = DemoRun(
            id=str(uuid4()),
            kind=kind,
            name=name,
            started_at=started_at.isoformat(),
        )
        async with self._lock:
            self._runs.insert(0, run)
            if len(self._runs) > self._max_entries:
                self._runs = self._runs[: self._max_entries]
            await self._persist_locked()
        return run.id

    async def end_run(
        self,
        run_id: str,
        *,
        ended_at: datetime,
        reason: str,
    ) -> None:
        """Finalize a run with end time + computed stats from the demo outbox."""
        # Tiny delay so any tail-end pipeline writes hit the SQLite WAL before
        # we query — the pipeline task is being cancelled in parallel.
        await anyio.sleep(0.3)

        stats = await self._compute_stats(run_id=run_id)

        async with self._lock:
            for r in self._runs:
                if r.id != run_id:
                    continue
                r.ended_at = ended_at.isoformat()
                r.ended_reason = reason
                r.frame_count = stats.get("frame_count")
                r.bird_count_avg = stats.get("bird_count_avg")
                r.bird_count_max = stats.get("bird_count_max")
                break
            await self._persist_locked()

    async def list_runs(self, limit: int = 50) -> list[DemoRun]:
        async with self._lock:
            return list(self._runs[: max(1, limit)])

    # ── internal ───────────────────────────────────────────────────────────

    async def _compute_stats(self, *, run_id: str) -> dict[str, Any]:
        async with self._lock:
            run = next((r for r in self._runs if r.id == run_id), None)
            if run is None:
                return {}
            started = run.started_at
            ended = run.ended_at

        # If end_run hasn't written ended_at yet (we're computing FOR end_run),
        # bound the query at "now."
        ended = ended or datetime.now(timezone.utc).isoformat()

        if not self._outbox_path.is_file():
            return {}

        try:
            async with aiosqlite.connect(self._outbox_path) as db:
                cur = await db.execute(
                    "SELECT count(*), "
                    "avg(json_extract(payload,'$.bird_count')), "
                    "max(json_extract(payload,'$.bird_count')) "
                    "FROM outbox "
                    "WHERE event_type='bird_detection' "
                    "AND created_at >= ? AND created_at <= ?",
                    (started, ended),
                )
                row = await cur.fetchone()
                await cur.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("demo_history.stats.failed", error=str(exc))
            return {}

        if not row:
            return {}
        return {
            "frame_count": int(row[0] or 0),
            "bird_count_avg": float(row[1]) if row[1] is not None else None,
            "bird_count_max": int(row[2]) if row[2] is not None else None,
        }

    async def _persist_locked(self) -> None:
        """Atomic write — .tmp then rename. Caller must hold `_lock`."""
        data = [asdict(r) for r in self._runs]
        text = json.dumps(data, indent=2)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")

        def _write() -> None:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(self._path)

        await anyio.to_thread.run_sync(_write)
