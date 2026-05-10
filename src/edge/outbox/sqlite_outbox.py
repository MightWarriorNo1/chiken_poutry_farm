"""SQLite-backed outbox with WAL mode.

- Writes are atomic and survive crashes.
- FIFO ordering per event type (sync drains by type).
- `attempts` column lets a future scheduler back off failing batches.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

import aiosqlite

from edge.domain.events import EventEnvelope, EventType

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    event_id        TEXT PRIMARY KEY,
    event_type      TEXT NOT NULL,
    schema_version  TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    payload         TEXT NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_outbox_type_created ON outbox(event_type, created_at);
"""


class SqliteOutbox:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def put(self, event: EventEnvelope) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT OR IGNORE INTO outbox(event_id, event_type, schema_version, "
            "created_at, payload, attempts) VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(event.event_id),
                event.event_type.value,
                event.schema_version,
                event.created_at.isoformat(),
                json.dumps(event.payload, default=str),
                event.attempts,
            ),
        )
        await self._db.commit()

    async def peek(self, event_type: EventType, limit: int) -> Sequence[EventEnvelope]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT event_id, event_type, schema_version, created_at, payload, attempts "
            "FROM outbox WHERE event_type = ? ORDER BY created_at ASC LIMIT ?",
            (event_type.value, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            EventEnvelope(
                event_id=UUID(row[0]),
                event_type=EventType(row[1]),
                schema_version=row[2],
                created_at=row[3],  # type: ignore[arg-type]  # pydantic parses ISO string
                payload=json.loads(row[4]),
                attempts=row[5],
            )
            for row in rows
        ]

    async def ack(self, event_ids: Sequence[UUID]) -> None:
        if not event_ids:
            return
        assert self._db is not None
        placeholders = ",".join("?" for _ in event_ids)
        await self._db.execute(
            f"DELETE FROM outbox WHERE event_id IN ({placeholders})",  # noqa: S608
            tuple(str(e) for e in event_ids),
        )
        await self._db.commit()

    async def nack(self, event_ids: Sequence[UUID]) -> None:
        if not event_ids:
            return
        assert self._db is not None
        placeholders = ",".join("?" for _ in event_ids)
        await self._db.execute(
            f"UPDATE outbox SET attempts = attempts + 1 "  # noqa: S608
            f"WHERE event_id IN ({placeholders})",
            tuple(str(e) for e in event_ids),
        )
        await self._db.commit()

    async def pending_count(self) -> int:
        assert self._db is not None
        cursor = await self._db.execute("SELECT COUNT(*) FROM outbox")
        row = await cursor.fetchone()
        await cursor.close()
        return int(row[0]) if row else 0

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
