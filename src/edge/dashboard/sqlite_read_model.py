"""SQLite-backed dashboard projection.

Lives in the *same* `outbox.db` file as the outbox so we have one backup story
and one disk location. Tables are prefixed `view_` to keep them visibly distinct
from the `outbox` table.

Per-entity tables hold only the *latest* state (`view_camera`, `view_sensor`,
`view_heartbeat`, ...). Sparkline tables (`view_series_*`) hold a rolling
window — oldest rows are trimmed inline on every insert so the projection
size stays bounded.

All writes go through `apply()`. The method dispatches on `event.event_type`
and is a no-op for unknown types — defensive so a new event variety doesn't
crash the engine.

Concurrency: one connection, all coroutines serialize through SQLite's
default locking. Workload is tiny (~5 writes/sec at PoC scale), so the
simpler model wins over a connection pool.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

from edge.dashboard.views import (
    AIModelView,
    AlertView,
    CameraSeriesView,
    CameraView,
    ManualWeightView,
    SensorSeriesView,
    SensorView,
    StatusView,
    TimePoint,
)
from edge.domain.events import EventEnvelope, EventType

log = structlog.get_logger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS view_camera (
    camera_id        TEXT PRIMARY KEY,
    shed_id          TEXT,
    flock_id         TEXT,
    zone_id          TEXT,
    model_version    TEXT,
    bird_count       INTEGER,
    density_score    REAL,
    confidence       REAL,
    captured_at      TEXT,
    snapshot_uri     TEXT
);

CREATE TABLE IF NOT EXISTS view_weight (
    camera_id              TEXT PRIMARY KEY,
    flock_id               TEXT,
    estimated_avg_weight_g REAL,
    confidence             REAL,
    bird_age_days          INTEGER,
    breed                  TEXT,
    captured_at            TEXT
);

CREATE TABLE IF NOT EXISTS view_huddling (
    camera_id           TEXT PRIMARY KEY,
    zone_id             TEXT,
    huddling_score      REAL,
    cluster_count       INTEGER,
    largest_cluster_pct REAL,
    captured_at         TEXT
);

CREATE TABLE IF NOT EXISTS view_sensor (
    sensor_id    TEXT PRIMARY KEY,
    sensor_type  TEXT,
    shed_id      TEXT,
    zone_id      TEXT,
    value        REAL,
    unit         TEXT,
    recorded_at  TEXT,
    quality      TEXT
);

CREATE TABLE IF NOT EXISTS view_heartbeat (
    device_id        TEXT PRIMARY KEY,
    status           TEXT,
    software_version TEXT,
    reported_at      TEXT,
    cpu_pct          REAL,
    memory_pct       REAL,
    storage_pct      REAL,
    outbox_pending   INTEGER,
    ai_models_json   TEXT,
    cameras_json     TEXT,
    sensors_json     TEXT
);

CREATE TABLE IF NOT EXISTS view_alert (
    event_id        TEXT PRIMARY KEY,
    alert_type      TEXT NOT NULL,
    severity        TEXT NOT NULL,
    source          TEXT NOT NULL,
    raised_at       TEXT NOT NULL,
    message         TEXT NOT NULL,
    shed_id         TEXT,
    zone_id         TEXT,
    flock_id        TEXT,
    camera_id       TEXT,
    sensor_id       TEXT,
    snapshot_uri    TEXT,
    correlation_key TEXT,
    metrics_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_view_alert_raised ON view_alert(raised_at DESC);

CREATE TABLE IF NOT EXISTS view_manual_weight (
    event_id         TEXT PRIMARY KEY,
    flock_id         TEXT NOT NULL,
    shed_id          TEXT,
    sampled_at       TEXT NOT NULL,
    flock_age_days   INTEGER,
    sample_count     INTEGER NOT NULL,
    average_weight_g REAL NOT NULL,
    min_weight_g     REAL,
    max_weight_g     REAL,
    notes            TEXT,
    operator         TEXT
);
CREATE INDEX IF NOT EXISTS idx_view_manual_sampled ON view_manual_weight(sampled_at DESC);

CREATE TABLE IF NOT EXISTS view_series_bird (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id  TEXT NOT NULL,
    t          TEXT NOT NULL,
    count      INTEGER NOT NULL,
    density    REAL NOT NULL,
    confidence REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_view_series_bird_cam ON view_series_bird(camera_id, id DESC);

CREATE TABLE IF NOT EXISTS view_series_huddling (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id  TEXT NOT NULL,
    t          TEXT NOT NULL,
    score      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_view_series_huddling_cam ON view_series_huddling(camera_id, id DESC);

CREATE TABLE IF NOT EXISTS view_series_sensor (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id  TEXT NOT NULL,
    t          TEXT NOT NULL,
    value      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_view_series_sensor_sid ON view_series_sensor(sensor_id, id DESC);
"""


class SqliteReadModel:
    def __init__(
        self,
        path: Path,
        *,
        series_size: int = 100,
        alerts_window: int = 200,
        manual_weights_window: int = 50,
    ) -> None:
        self._path = path
        self._series_size = series_size
        self._alerts_window = alerts_window
        self._manual_window = manual_weights_window
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    # ── write side ─────────────────────────────────────────────────────────

    async def apply(self, event: EventEnvelope) -> None:
        handler = _DISPATCH.get(event.event_type)
        if handler is None:
            return
        try:
            await handler(self, event.payload)
        except Exception as exc:  # noqa: BLE001
            log.exception(
                "dashboard.read_model.apply.failed",
                event_type=event.event_type.value,
                error=str(exc),
            )
            # Roll back the partial transaction so a half-written row doesn't
            # poison the next successful apply (sqlite3 auto-begins a tx).
            db = self._db
            if db is not None:
                try:
                    await db.rollback()
                except Exception as rb_exc:  # noqa: BLE001
                    log.exception(
                        "dashboard.read_model.rollback.failed", error=str(rb_exc)
                    )

    async def _apply_bird_detection(self, p: dict[str, Any]) -> None:
        if not p.get("camera_id"):
            return
        db = self._require_db()
        await db.execute(
            "INSERT INTO view_camera "
            "(camera_id, shed_id, flock_id, zone_id, model_version, bird_count, "
            " density_score, confidence, captured_at, snapshot_uri) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(camera_id) DO UPDATE SET "
            "  shed_id=excluded.shed_id, flock_id=excluded.flock_id, "
            "  zone_id=excluded.zone_id, model_version=excluded.model_version, "
            "  bird_count=excluded.bird_count, density_score=excluded.density_score, "
            "  confidence=excluded.confidence, captured_at=excluded.captured_at, "
            "  snapshot_uri=excluded.snapshot_uri",
            (
                p.get("camera_id"),
                p.get("shed_id"),
                p.get("flock_id"),
                p.get("zone_id"),
                p.get("model_version"),
                p.get("bird_count"),
                p.get("density_score"),
                p.get("confidence"),
                p.get("captured_at"),
                p.get("snapshot_uri"),
            ),
        )
        await db.execute(
            "INSERT INTO view_series_bird (camera_id, t, count, density, confidence) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                p.get("camera_id"),
                p.get("captured_at"),
                p.get("bird_count") or 0,
                p.get("density_score") or 0.0,
                p.get("confidence") or 0.0,
            ),
        )
        await self._trim_series(
            "view_series_bird", key_col="camera_id", key=p.get("camera_id")
        )
        await db.commit()

    async def _apply_weight_estimate(self, p: dict[str, Any]) -> None:
        if not p.get("camera_id"):
            return
        db = self._require_db()
        await db.execute(
            "INSERT INTO view_weight "
            "(camera_id, flock_id, estimated_avg_weight_g, confidence, "
            " bird_age_days, breed, captured_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(camera_id) DO UPDATE SET "
            "  flock_id=excluded.flock_id, "
            "  estimated_avg_weight_g=excluded.estimated_avg_weight_g, "
            "  confidence=excluded.confidence, "
            "  bird_age_days=excluded.bird_age_days, "
            "  breed=excluded.breed, "
            "  captured_at=excluded.captured_at",
            (
                p.get("camera_id"),
                p.get("flock_id"),
                p.get("estimated_avg_weight_g"),
                p.get("confidence"),
                p.get("bird_age_days"),
                p.get("breed"),
                p.get("captured_at"),
            ),
        )
        await db.commit()

    async def _apply_huddling_score(self, p: dict[str, Any]) -> None:
        if not p.get("camera_id"):
            return
        db = self._require_db()
        await db.execute(
            "INSERT INTO view_huddling "
            "(camera_id, zone_id, huddling_score, cluster_count, "
            " largest_cluster_pct, captured_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(camera_id) DO UPDATE SET "
            "  zone_id=excluded.zone_id, "
            "  huddling_score=excluded.huddling_score, "
            "  cluster_count=excluded.cluster_count, "
            "  largest_cluster_pct=excluded.largest_cluster_pct, "
            "  captured_at=excluded.captured_at",
            (
                p.get("camera_id"),
                p.get("zone_id"),
                p.get("huddling_score"),
                p.get("cluster_count"),
                p.get("largest_cluster_pct"),
                p.get("captured_at"),
            ),
        )
        await db.execute(
            "INSERT INTO view_series_huddling (camera_id, t, score) VALUES (?, ?, ?)",
            (
                p.get("camera_id"),
                p.get("captured_at"),
                p.get("huddling_score") or 0.0,
            ),
        )
        await self._trim_series(
            "view_series_huddling", key_col="camera_id", key=p.get("camera_id")
        )
        await db.commit()

    async def _apply_sensor_reading(self, p: dict[str, Any]) -> None:
        if not p.get("sensor_id"):
            return
        db = self._require_db()
        await db.execute(
            "INSERT INTO view_sensor "
            "(sensor_id, sensor_type, shed_id, zone_id, value, unit, recorded_at, quality) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(sensor_id) DO UPDATE SET "
            "  sensor_type=excluded.sensor_type, shed_id=excluded.shed_id, "
            "  zone_id=excluded.zone_id, value=excluded.value, unit=excluded.unit, "
            "  recorded_at=excluded.recorded_at, quality=excluded.quality",
            (
                p.get("sensor_id"),
                p.get("sensor_type"),
                p.get("shed_id"),
                p.get("zone_id"),
                p.get("value"),
                p.get("unit"),
                p.get("recorded_at"),
                p.get("quality"),
            ),
        )
        await db.execute(
            "INSERT INTO view_series_sensor (sensor_id, t, value) VALUES (?, ?, ?)",
            (p.get("sensor_id"), p.get("recorded_at"), p.get("value") or 0.0),
        )
        await self._trim_series(
            "view_series_sensor", key_col="sensor_id", key=p.get("sensor_id")
        )
        await db.commit()

    async def _apply_heartbeat(self, p: dict[str, Any]) -> None:
        if not p.get("device_id"):
            return
        db = self._require_db()
        await db.execute(
            "INSERT INTO view_heartbeat "
            "(device_id, status, software_version, reported_at, "
            " cpu_pct, memory_pct, storage_pct, outbox_pending, "
            " ai_models_json, cameras_json, sensors_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(device_id) DO UPDATE SET "
            "  status=excluded.status, software_version=excluded.software_version, "
            "  reported_at=excluded.reported_at, cpu_pct=excluded.cpu_pct, "
            "  memory_pct=excluded.memory_pct, storage_pct=excluded.storage_pct, "
            "  outbox_pending=excluded.outbox_pending, "
            "  ai_models_json=excluded.ai_models_json, "
            "  cameras_json=excluded.cameras_json, "
            "  sensors_json=excluded.sensors_json",
            (
                p.get("device_id"),
                p.get("status"),
                p.get("software_version"),
                p.get("reported_at"),
                p.get("cpu_pct"),
                p.get("memory_pct"),
                p.get("storage_pct"),
                p.get("outbox_pending"),
                json.dumps(p.get("ai_models") or []),
                json.dumps(p.get("cameras") or []),
                json.dumps(p.get("sensors") or []),
            ),
        )
        await db.commit()

    async def _apply_alert(self, p: dict[str, Any]) -> None:
        if not p.get("event_id") or not p.get("alert_type"):
            return
        db = self._require_db()
        await db.execute(
            "INSERT OR IGNORE INTO view_alert "
            "(event_id, alert_type, severity, source, raised_at, message, "
            " shed_id, zone_id, flock_id, camera_id, sensor_id, "
            " snapshot_uri, correlation_key, metrics_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                p.get("event_id"),
                p.get("alert_type"),
                p.get("severity"),
                p.get("source"),
                p.get("raised_at"),
                p.get("message"),
                p.get("shed_id"),
                p.get("zone_id"),
                p.get("flock_id"),
                p.get("camera_id"),
                p.get("sensor_id"),
                p.get("snapshot_uri"),
                p.get("correlation_key"),
                json.dumps(p.get("metrics") or {}),
            ),
        )
        # Rolling window: drop oldest beyond cap.
        await db.execute(
            "DELETE FROM view_alert WHERE event_id IN ("
            "  SELECT event_id FROM view_alert "
            "  ORDER BY raised_at DESC LIMIT -1 OFFSET ?"
            ")",
            (self._alerts_window,),
        )
        await db.commit()

    async def _apply_manual_weight(self, p: dict[str, Any]) -> None:
        if not p.get("event_id") or not p.get("flock_id"):
            return
        db = self._require_db()
        await db.execute(
            "INSERT OR IGNORE INTO view_manual_weight "
            "(event_id, flock_id, shed_id, sampled_at, flock_age_days, "
            " sample_count, average_weight_g, min_weight_g, max_weight_g, "
            " notes, operator) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                p.get("event_id"),
                p.get("flock_id"),
                p.get("shed_id"),
                p.get("sampled_at"),
                p.get("flock_age_days"),
                p.get("sample_count"),
                p.get("average_weight_g"),
                p.get("min_weight_g"),
                p.get("max_weight_g"),
                p.get("notes"),
                p.get("operator"),
            ),
        )
        await db.execute(
            "DELETE FROM view_manual_weight WHERE event_id IN ("
            "  SELECT event_id FROM view_manual_weight "
            "  ORDER BY sampled_at DESC LIMIT -1 OFFSET ?"
            ")",
            (self._manual_window,),
        )
        await db.commit()

    async def _trim_series(self, table: str, *, key_col: str, key: Any) -> None:
        """Keep last `series_size` rows per key. Inline trim — cheap at N=100."""
        if key is None:
            return
        db = self._require_db()
        await db.execute(
            f"DELETE FROM {table} WHERE id IN ("  # noqa: S608 — table+col are hardcoded
            f"  SELECT id FROM {table} WHERE {key_col} = ? "
            f"  ORDER BY id DESC LIMIT -1 OFFSET ?"
            f")",
            (key, self._series_size),
        )

    # ── read side ──────────────────────────────────────────────────────────

    async def get_status(self) -> StatusView:
        db = self._require_db()
        async with db.execute("SELECT * FROM view_heartbeat LIMIT 1") as cur:
            row = await cur.fetchone()
        camera_count = await self._scalar_count("view_camera")
        sensor_count = await self._scalar_count("view_sensor")
        open_alert_count = await self._scalar_count("view_alert")

        if row is None:
            return StatusView(
                device_id="unknown",
                software_version="0.0.0",
                camera_count=camera_count,
                sensor_count=sensor_count,
                open_alert_count=open_alert_count,
            )

        ai_models_raw = json.loads(row["ai_models_json"] or "[]")
        return StatusView(
            device_id=row["device_id"],
            software_version=row["software_version"] or "0.0.0",
            status=row["status"] or "unknown",
            reported_at=_to_dt(row["reported_at"]),
            cpu_pct=row["cpu_pct"],
            memory_pct=row["memory_pct"],
            storage_pct=row["storage_pct"],
            outbox_pending=int(row["outbox_pending"] or 0),
            ai_models=[AIModelView(**m) for m in ai_models_raw if isinstance(m, dict)],
            camera_count=camera_count,
            sensor_count=sensor_count,
            open_alert_count=open_alert_count,
        )

    async def list_cameras(self) -> list[CameraView]:
        db = self._require_db()
        # LEFT JOIN so a camera shows up as soon as we see *any* event for it.
        async with db.execute(
            "SELECT c.*, "
            "       w.estimated_avg_weight_g, w.confidence AS weight_confidence, "
            "       w.bird_age_days, w.breed, w.captured_at AS weight_at, "
            "       h.huddling_score, h.cluster_count, h.largest_cluster_pct, "
            "       h.captured_at AS huddling_at "
            "FROM view_camera c "
            "LEFT JOIN view_weight w ON w.camera_id = c.camera_id "
            "LEFT JOIN view_huddling h ON h.camera_id = c.camera_id "
            "ORDER BY c.camera_id ASC"
        ) as cur:
            rows = await cur.fetchall()
        return [
            CameraView(
                camera_id=r["camera_id"],
                shed_id=r["shed_id"],
                flock_id=r["flock_id"],
                zone_id=r["zone_id"],
                model_version=r["model_version"],
                bird_count=r["bird_count"],
                density_score=r["density_score"],
                confidence=r["confidence"],
                last_frame_at=_to_dt(r["captured_at"]),
                snapshot_uri=r["snapshot_uri"],
                huddling_score=r["huddling_score"],
                cluster_count=r["cluster_count"],
                largest_cluster_pct=r["largest_cluster_pct"],
                huddling_at=_to_dt(r["huddling_at"]),
                estimated_avg_weight_g=r["estimated_avg_weight_g"],
                weight_confidence=r["weight_confidence"],
                bird_age_days=r["bird_age_days"],
                breed=r["breed"],
                weight_at=_to_dt(r["weight_at"]),
            )
            for r in rows
        ]

    async def get_camera_series(self, camera_id: str, limit: int) -> CameraSeriesView:
        db = self._require_db()
        bird = await self._fetch_series(
            "SELECT t, count, density, confidence FROM view_series_bird "
            "WHERE camera_id = ? ORDER BY id DESC LIMIT ?",
            (camera_id, limit),
            ("count", "density", "confidence"),
        )
        huddle = await self._fetch_series(
            "SELECT t, score FROM view_series_huddling "
            "WHERE camera_id = ? ORDER BY id DESC LIMIT ?",
            (camera_id, limit),
            ("score",),
        )
        return CameraSeriesView(
            camera_id=camera_id,
            bird_count=bird,
            huddling=huddle,
        )

    async def list_sensors(self) -> list[SensorView]:
        db = self._require_db()
        async with db.execute("SELECT * FROM view_sensor ORDER BY sensor_id ASC") as cur:
            rows = await cur.fetchall()
        return [
            SensorView(
                sensor_id=r["sensor_id"],
                sensor_type=r["sensor_type"] or "unknown",
                shed_id=r["shed_id"],
                zone_id=r["zone_id"],
                value=r["value"],
                unit=r["unit"],
                recorded_at=_to_dt(r["recorded_at"]),
                quality=r["quality"],
            )
            for r in rows
        ]

    async def get_sensor_series(self, sensor_id: str, limit: int) -> SensorSeriesView:
        points = await self._fetch_series(
            "SELECT t, value FROM view_series_sensor "
            "WHERE sensor_id = ? ORDER BY id DESC LIMIT ?",
            (sensor_id, limit),
            ("value",),
        )
        return SensorSeriesView(sensor_id=sensor_id, points=points)

    async def list_alerts(self, limit: int) -> list[AlertView]:
        db = self._require_db()
        async with db.execute(
            "SELECT * FROM view_alert ORDER BY raised_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
        out: list[AlertView] = []
        for r in rows:
            metrics_raw = json.loads(r["metrics_json"] or "{}")
            out.append(
                AlertView(
                    event_id=r["event_id"],
                    alert_type=r["alert_type"],
                    severity=r["severity"],
                    source=r["source"],
                    raised_at=_to_dt(r["raised_at"]) or _epoch(),
                    message=r["message"],
                    shed_id=r["shed_id"],
                    zone_id=r["zone_id"],
                    flock_id=r["flock_id"],
                    camera_id=r["camera_id"],
                    sensor_id=r["sensor_id"],
                    snapshot_uri=r["snapshot_uri"],
                    correlation_key=r["correlation_key"],
                    metrics=metrics_raw if isinstance(metrics_raw, dict) else {},
                )
            )
        return out

    async def list_manual_weights(self, limit: int) -> list[ManualWeightView]:
        db = self._require_db()
        async with db.execute(
            "SELECT * FROM view_manual_weight ORDER BY sampled_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
        return [
            ManualWeightView(
                event_id=r["event_id"],
                flock_id=r["flock_id"],
                shed_id=r["shed_id"],
                sampled_at=_to_dt(r["sampled_at"]) or _epoch(),
                flock_age_days=r["flock_age_days"],
                sample_count=r["sample_count"],
                average_weight_g=r["average_weight_g"],
                min_weight_g=r["min_weight_g"],
                max_weight_g=r["max_weight_g"],
                notes=r["notes"],
                operator=r["operator"],
            )
            for r in rows
        ]

    # ── helpers ────────────────────────────────────────────────────────────

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SqliteReadModel.init() not called")
        return self._db

    async def _scalar_count(self, table: str) -> int:
        db = self._require_db()
        async with db.execute(f"SELECT COUNT(*) FROM {table}") as cur:  # noqa: S608
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def _fetch_series(
        self,
        sql: str,
        params: tuple[Any, ...],
        value_cols: Iterable[str],
    ) -> list[TimePoint]:
        db = self._require_db()
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        # Reverse so the UI gets oldest → newest.
        points: list[TimePoint] = []
        for r in reversed(rows):
            t = _to_dt(r["t"])
            if t is None:
                continue
            values = {col: float(r[col] or 0.0) for col in value_cols}
            points.append(TimePoint(t=t, values=values))
        return points


# ── dispatch table ─────────────────────────────────────────────────────────

_DISPATCH = {
    EventType.BIRD_DETECTION: SqliteReadModel._apply_bird_detection,
    EventType.WEIGHT_ESTIMATE: SqliteReadModel._apply_weight_estimate,
    EventType.HUDDLING_SCORE: SqliteReadModel._apply_huddling_score,
    EventType.SENSOR_READING: SqliteReadModel._apply_sensor_reading,
    EventType.DEVICE_HEARTBEAT: SqliteReadModel._apply_heartbeat,
    EventType.ALERT: SqliteReadModel._apply_alert,
    EventType.MANUAL_WEIGHT_SAMPLE: SqliteReadModel._apply_manual_weight,
}


def _to_dt(val: Any) -> Any:
    """Pydantic will accept an ISO string just fine, so we just normalise None."""
    if val is None or val == "":
        return None
    return val


def _epoch() -> Any:
    """Sentinel timestamp used when a required `datetime` field is missing —
    shouldn't happen in practice but pydantic won't accept None."""
    from datetime import datetime, timezone  # noqa: PLC0415
    return datetime.fromtimestamp(0, tz=timezone.utc)
