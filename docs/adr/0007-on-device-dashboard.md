# ADR 0007 — On-device dashboard

## Status
Accepted (2026-05-11).

## Context

The customer-facing dashboard lives in a separate repo and is being built by another team. But the edge box itself needs a *local* view of what it's doing — for three concrete reasons:

1. **Field debugging.** When a farm calls and says "the AI isn't working," the on-site tech needs to see camera frames, bird counts, sensor values, and alerts *without* relying on cloud connectivity or VPN'ing back to a cloud dashboard.
2. **PoC demos.** The PoC spec ([POC Requirements](../../POC%20Requirements%20-%20Prosper%20PoultryVision%20AI.docx)) asks for §6/§7 screens. Until the cloud team ships them, we still need something to show in customer demos.
3. **Sync independence.** The outbox is FIFO-and-drain — events are deleted after cloud sync. Reading the outbox for a UI would show "nothing here" the moment sync is healthy. We need a durable *projection* keyed by entity.

## Decision

Add a **read-only on-device dashboard** to this repo:
- A **ReadModel** projection (SQLite, in the same `outbox.db` file but with `view_*` tables) populated by a `ProjectingOutbox` decorator that tees every event the pipelines produce.
- A **FastAPI** server hosting JSON endpoints + an SSE live feed on `127.0.0.1:8090` (configurable).
- A **React + Vite + Tailwind + Recharts** SPA with four tabs: Overview, Cameras, Sensors, Alerts.
- The server runs as another **pipeline** inside the same `anyio` task group as the rest of the edge — one process, one signal handler.

## Architectural fit

The dashboard slots into the existing hexagonal layout without disturbing anything:

```
FramePipeline ──┐
SensorPipeline ─┼─► ProjectingOutbox  ─► AlertingOutbox ─► SqliteOutbox ─► SyncPipeline ─► cloud
HeartbeatPipe ──┘    │
                     ├─► SqliteReadModel (view_* tables)  ─◄── FastAPI /api/*
                     └─► EventBus                          ─◄── FastAPI /events (SSE)
```

- `ProjectingOutbox` and `AlertingOutbox` are *Outbox decorators* — pipelines see a regular `Outbox` interface. No domain or pipeline code changed.
- The read model is a **projection**, not a queue: writes are idempotent upserts keyed by `camera_id` / `sensor_id` / `device_id`, plus rolling windows for alerts/manual-weights/series.
- The EventBus is in-process pub/sub with bounded queues; slow subscribers have their oldest events dropped so the publisher (the hot path) never stalls.

## Why these specific choices

| Question | Choice | Why |
|---|---|---|
| Project alongside writes, or on-read? | **On write (ProjectingOutbox tee)** | The outbox drain rate is unpredictable. Projecting on write means the read model survives sync. |
| Same DB file or separate? | **Same `outbox.db`** | One backup story, one disk location. `view_*` prefix makes tables obviously distinct. |
| Web framework? | **FastAPI** | Already on pydantic; domain models double as response schemas via `views.py`. |
| ASGI server? | **uvicorn, in-process** | One log stream, one shutdown path. `install_signal_handlers=False` so main.py owns SIGTERM/SIGINT. |
| Live updates? | **SSE** | One-way is all we need; works behind any proxy; auto-reconnects in browsers. |
| Frontend? | **React + Vite + Tailwind + Recharts** | Build-once → static dist served by FastAPI. No SSR runtime. |
| Bind address? | **127.0.0.1 default** | Safe default; override `EDGE_DASHBOARD__HOST=0.0.0.0` for LAN access. |
| Auth? | **None for PoC** | Local-only by default; the edge box is on a private network. Add bearer token later if we expose it. |

## What we explicitly didn't do

- **No write endpoints.** Manual weight entry stays in [scripts/submit_manual_weight.py](../../scripts/submit_manual_weight.py). The dashboard is purely a read side.
- **No alert lifecycle.** Acknowledge / resolve / mark-false-positive belongs to the cloud per [ADR 0006](0006-alert-engine.md). The edge only ever emits alerts in the `open` state.
- **No replay buffer in the bus.** Late subscribers don't get history — they pull state from SQLite via `/api/*` instead.
- **No health risk score yet.** That gap ([POC §6.8](../../POC%20Requirements%20-%20Prosper%20PoultryVision%20AI.docx)) is tracked separately so it can be reviewed independently.

## Failure modes

| Failure | Behavior |
|---|---|
| Projection write fails (bad payload, disk full) | Logged + rolled back via `db.rollback()`; event persistence and sync unaffected. |
| EventBus subscriber slow | Their oldest events drop (`WouldBlock` → log + continue); publisher never blocks. |
| Browser disconnects | SSE handler exits via `request.is_disconnected()`; subscriber slot freed. |
| Disk full | SQLite write errors propagate up to the tee, which logs and continues; pipelines stay alive. |
| Port 8090 already in use | Uvicorn raises; the task group propagates the cancellation and the edge process exits with a clear log line. |

## Trade-offs & known limits

- **One process for everything.** A runaway dashboard request can in principle steal CPU from inference. At PoC volumes (one farm, ~5 fps total) this is fine; revisit if a request ever blocks a frame.
- **SSE through ASGI test transports is awkward.** End-to-end SSE behavior is exercised by `tests/unit/test_event_bus.py` and `test_eventbus_publishes_what_outbox_writes` rather than streaming through `httpx.ASGITransport`, which buffers chunks and doesn't honor anyio cancellation cleanly.
- **No DB migration story for `view_*` tables.** They're rebuilt from `CREATE TABLE IF NOT EXISTS` on every boot; schema changes will need a small migration helper, but at PoC the tables are append-projections that can be dropped and rebuilt.

## Future extensions

- **Health Risk Score** (POC §6.8) — combine weight gap, huddling, temp, humidity, etc. into Low/Medium/High/Critical. Tracked separately.
- **Manual weight entry from the UI** — add `POST /api/manual-weights` and a small form.
- **Auth.** Bearer token via `EDGE_DASHBOARD__AUTH_TOKEN` env var when we expose the port beyond `127.0.0.1`.
- **Per-camera detail page.** Bigger sparklines, last 24h, snapshot gallery.
