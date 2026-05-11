"""FastAPI app factory for the on-device dashboard.

This module *builds* the app — it does not run it. The
[`DashboardPipeline`](../pipelines/dashboard_pipeline.py) hosts the app via
uvicorn inside the main anyio task group so we have one process, one logger,
one shutdown path.

Endpoints intentionally mirror the ReadModel query surface 1:1 so the React UI
has a flat, predictable API. SSE (`/events`) and sparkline series (`/api/.../series`)
are layered in by Phase 4.

`/api/config/sensor-thresholds` is the one cross-module dependency — the
ReadModel doesn't know per-sensor thresholds (those live in EdgeConfig). The
server takes a small callable that returns the threshold map at request time,
which keeps the ReadModel ignorant of config and lets the dashboard surface
in-range/out-of-range badges anyway.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anyio
import structlog
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from edge.config import DashboardSettings
from edge.dashboard.event_bus import EventBus
from edge.dashboard.read_model import ReadModel
from edge.dashboard.views import (
    AlertView,
    CameraSeriesView,
    CameraView,
    LiveEventView,
    ManualWeightView,
    SensorSeriesView,
    SensorView,
    StatusView,
)

log = structlog.get_logger(__name__)

# Sensor threshold map: { sensor_id: (min_or_None, max_or_None) }. The server
# layer takes a *callable* that returns the current map so EdgeConfig hot-reloads
# are picked up without restarting the dashboard.
ThresholdProvider = Callable[[], dict[str, tuple[float | None, float | None]]]


def _no_thresholds() -> dict[str, tuple[float | None, float | None]]:
    return {}


def create_app(
    *,
    read_model: ReadModel,
    event_bus: EventBus,
    settings: DashboardSettings,
    threshold_provider: ThresholdProvider = _no_thresholds,
    static_dir: Path | None = None,
) -> FastAPI:
    """Build a FastAPI app wired to a specific ReadModel + EventBus."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info(
            "dashboard.app.startup",
            host=settings.host,
            port=settings.port,
            static_dir=str(static_dir) if static_dir else None,
        )
        yield
        log.info("dashboard.app.shutdown")

    app = FastAPI(
        title="Prosper EdgeBox Dashboard",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # Stash dependencies on app.state so route handlers can reach them via Request.
    app.state.read_model = read_model
    app.state.event_bus = event_bus
    app.state.settings = settings
    app.state.threshold_provider = threshold_provider

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET"],
            allow_headers=["*"],
        )

    app.include_router(_build_api_router(), prefix="/api")
    app.include_router(_build_live_router())

    _mount_static(app, static_dir)

    return app


# ── API routes ──────────────────────────────────────────────────────────────


def _build_api_router() -> APIRouter:
    r = APIRouter()

    @r.get("/status", response_model=StatusView)
    async def status(request: Request) -> StatusView:
        rm: ReadModel = request.app.state.read_model
        return await rm.get_status()

    @r.get("/cameras", response_model=list[CameraView])
    async def cameras(request: Request) -> list[CameraView]:
        rm: ReadModel = request.app.state.read_model
        return await rm.list_cameras()

    @r.get("/cameras/{camera_id}/series", response_model=CameraSeriesView)
    async def camera_series(
        camera_id: str,
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> CameraSeriesView:
        rm: ReadModel = request.app.state.read_model
        return await rm.get_camera_series(camera_id, limit)

    @r.get("/sensors", response_model=list[SensorView])
    async def sensors(request: Request) -> list[SensorView]:
        rm: ReadModel = request.app.state.read_model
        provider: ThresholdProvider = request.app.state.threshold_provider
        thresholds = provider() or {}
        out = await rm.list_sensors()
        # Decorate each row with its threshold + in_range flag.
        for s in out:
            lo, hi = thresholds.get(s.sensor_id, (None, None))
            s.threshold_min = lo
            s.threshold_max = hi
            if s.value is None:
                s.in_range = None
            else:
                ok_low = lo is None or s.value >= lo
                ok_high = hi is None or s.value <= hi
                s.in_range = ok_low and ok_high
        return out

    @r.get("/sensors/{sensor_id}/series", response_model=SensorSeriesView)
    async def sensor_series(
        sensor_id: str,
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> SensorSeriesView:
        rm: ReadModel = request.app.state.read_model
        return await rm.get_sensor_series(sensor_id, limit)

    @r.get("/alerts", response_model=list[AlertView])
    async def alerts(
        request: Request, limit: int = Query(default=50, ge=1, le=500)
    ) -> list[AlertView]:
        rm: ReadModel = request.app.state.read_model
        return await rm.list_alerts(limit)

    @r.get("/manual-weights", response_model=list[ManualWeightView])
    async def manual_weights(
        request: Request, limit: int = Query(default=20, ge=1, le=200)
    ) -> list[ManualWeightView]:
        rm: ReadModel = request.app.state.read_model
        return await rm.list_manual_weights(limit)

    return r


# ── SSE live feed ───────────────────────────────────────────────────────────


def _build_live_router() -> APIRouter:
    """Streaming endpoint the React UI subscribes to so cards animate live.

    Each subscriber gets a bounded queue inside the EventBus; slow clients get
    their oldest events dropped so the publisher (the hot path) never stalls.
    """
    r = APIRouter()

    @r.get("/events")
    async def events(request: Request) -> EventSourceResponse:
        bus: EventBus = request.app.state.event_bus

        async def stream() -> AsyncIterator[dict[str, Any]]:
            # Send a hello frame so the client can confirm the stream is live.
            yield {
                "event": "hello",
                "data": json.dumps(
                    {"at": datetime.now(timezone.utc).isoformat()}
                ),
            }
            async with bus.subscribe() as recv:
                async for envelope in recv:
                    if await request.is_disconnected():
                        return
                    view = LiveEventView(
                        type=envelope.event_type.value,
                        at=envelope.created_at,
                        payload=envelope.payload,
                    )
                    yield {
                        "event": envelope.event_type.value,
                        "data": view.model_dump_json(),
                    }

        # ping_event keeps proxies / browsers happy on quiet streams.
        return EventSourceResponse(stream(), ping=15)

    return r


# ── Static mount (React build) ──────────────────────────────────────────────


def _mount_static(app: FastAPI, static_dir: Path | None) -> None:
    """Serve the React build if present, otherwise a placeholder page.

    Layout produced by `vite build`:
      dist/index.html
      dist/assets/index-<hash>.{js,css}
      dist/vite.svg

    We mount `/assets` to `dist/assets` (cache-bustable hashed files), then
    add a catch-all SPA fallback that returns `index.html` for any unmatched
    non-`/api` path. API + SSE routes are already registered, so they always win.
    """
    if static_dir is not None and static_dir.is_dir():
        index = static_dir / "index.html"
        assets = static_dir / "assets"
        if index.is_file():
            if assets.is_dir():
                app.mount(
                    "/assets",
                    StaticFiles(directory=assets),
                    name="dashboard-assets",
                )

            @app.get("/{full_path:path}", include_in_schema=False)
            async def spa_fallback(full_path: str) -> Any:
                # Defensive: API + SSE routes are mounted before this, but if
                # somehow this matches first, refuse to swallow them.
                if full_path.startswith(("api/", "events")):
                    raise HTTPException(status_code=404)
                target = static_dir / full_path
                if full_path and target.is_file():
                    return FileResponse(target)
                return FileResponse(index)

            return

    # No build yet — friendly placeholder so devs aren't confused.
    @app.get("/", include_in_schema=False)
    async def placeholder() -> JSONResponse:
        return JSONResponse(
            {
                "status": "dashboard backend running",
                "note": "React build not present. Run `cd src/edge/dashboard/web && "
                "npm install && npm run build` to generate it.",
                "api_docs": "/api/docs",
                "endpoints": [
                    "/api/status",
                    "/api/cameras",
                    "/api/sensors",
                    "/api/alerts",
                    "/api/manual-weights",
                    "/events  (SSE)",
                ],
            }
        )


# ── Threshold provider helper for main.py ──────────────────────────────────


def threshold_provider_from_supervisor(
    sensor_supervisor: Any,
) -> ThresholdProvider:
    """Bridge: pull the current sensor-threshold map out of the SensorSupervisor.

    Loose duck-typing so we don't import the supervisor at module scope and
    create a circular dep. We rely on the supervisor exposing a `thresholds`
    property returning `{ sensor_id: (min, max) }` — added in Phase 2.
    """

    def _provide() -> dict[str, tuple[float | None, float | None]]:
        try:
            raw = getattr(sensor_supervisor, "thresholds", None)
            if callable(raw):
                raw = raw()
            return raw or {}
        except Exception as exc:  # noqa: BLE001
            log.debug("dashboard.threshold_provider.failed", error=str(exc))
            return {}

    return _provide


async def wait_for_cancel() -> None:
    """Small helper used by integration tests to keep the app alive until
    the test scope cancels it."""
    await anyio.sleep_forever()
