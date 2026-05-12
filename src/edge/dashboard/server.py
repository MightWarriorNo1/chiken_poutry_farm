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
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from edge.config import DashboardSettings
from edge.dashboard.adhoc import AdhocManager
from edge.dashboard.camera_sources import classify_source, type_label
from edge.dashboard.demo import DemoManager
from edge.dashboard.discovery import (
    discover_csi,
    discover_file,
    discover_rtsp,
    discover_usb,
)
from edge.dashboard.event_bus import EventBus
from edge.dashboard.read_model import ReadModel
from edge.dashboard.stream_registry import StreamRegistry
from edge.dashboard.views import (
    AdhocStartRequest,
    AdhocStatusView,
    AlertView,
    CameraSeriesView,
    CameraSourceView,
    CameraView,
    DemoImageView,
    DemoRunView,
    DemoStartImageRequest,
    DemoStartRequest,
    DemoStatusView,
    DemoVideoView,
    DiscoveredDeviceView,
    LiveEventView,
    ManualWeightView,
    SensorSeriesView,
    SensorView,
    StatusView,
)
from edge.supervisors.camera_supervisor import CameraSupervisor

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
    stream_registry: StreamRegistry | None = None,
    camera_supervisor: CameraSupervisor | None = None,
    demo_manager: DemoManager | None = None,
    adhoc_manager: AdhocManager | None = None,
    demo_videos_dir: Path | None = None,
) -> FastAPI:
    """Build a FastAPI app wired to a specific ReadModel + EventBus."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info(
            "dashboard.app.startup",
            host=settings.host,
            port=settings.port,
            static_dir=str(static_dir) if static_dir else None,
            streams=bool(stream_registry),
            demo=bool(demo_manager),
            adhoc=bool(adhoc_manager),
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
    app.state.stream_registry = stream_registry
    app.state.camera_supervisor = camera_supervisor
    app.state.demo_manager = demo_manager
    app.state.adhoc_manager = adhoc_manager
    app.state.demo_videos_dir = demo_videos_dir

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    app.include_router(_build_api_router(), prefix="/api")
    app.include_router(_build_stream_router(), prefix="/api")
    app.include_router(_build_sources_router(), prefix="/api")
    app.include_router(_build_demo_router(), prefix="/api")
    app.include_router(_build_discovery_router(), prefix="/api")
    app.include_router(_build_adhoc_router(), prefix="/api")
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


# ── MJPEG camera stream ─────────────────────────────────────────────────────


_MJPEG_BOUNDARY = "frame"


def _mjpeg_part(jpeg: bytes) -> bytes:
    """One multipart/x-mixed-replace chunk for an MJPEG response."""
    return (
        f"--{_MJPEG_BOUNDARY}\r\n"
        f"Content-Type: image/jpeg\r\n"
        f"Content-Length: {len(jpeg)}\r\n\r\n"
    ).encode("ascii") + jpeg + b"\r\n"


def _build_stream_router() -> APIRouter:
    """`/api/cameras/{camera_id}/stream` — MJPEG of the annotated live feed.

    The frame source feeds the broadcaster; this endpoint just relays whatever
    JPEGs the broadcaster hands us. Pure I/O — no AI, no decode.
    """
    r = APIRouter()

    @r.get("/cameras/{camera_id}/stream", include_in_schema=False)
    async def stream(camera_id: str, request: Request) -> StreamingResponse:
        registry: StreamRegistry | None = request.app.state.stream_registry
        if registry is None:
            raise HTTPException(
                status_code=503, detail="Live streaming not configured on this device"
            )
        broadcaster = registry.get(camera_id)
        if broadcaster is None:
            raise HTTPException(
                status_code=404,
                detail=f"No live stream available for camera_id={camera_id!r}",
            )

        async def gen() -> AsyncIterator[bytes]:
            async with broadcaster.subscribe() as recv:
                async for jpeg in recv:
                    if await request.is_disconnected():
                        return
                    yield _mjpeg_part(jpeg)

        return StreamingResponse(
            gen(),
            media_type=f"multipart/x-mixed-replace; boundary={_MJPEG_BOUNDARY}",
            headers={
                # Browser + any intermediate proxy: don't cache, don't buffer.
                "Cache-Control": "no-cache, private",
                "Pragma": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return r


# ── Camera sources / type browser (Phase 2) ────────────────────────────────


def _build_sources_router() -> APIRouter:
    """`/api/cameras/sources` — every configured camera with its source-type
    classification and connection status.

    Powered by the CameraSupervisor (which sees both cloud config and demo
    extras) decorated with FrameBroadcaster signals.
    """
    r = APIRouter()

    @r.get("/cameras/sources", response_model=list[CameraSourceView])
    async def sources(request: Request) -> list[CameraSourceView]:
        sup: CameraSupervisor | None = request.app.state.camera_supervisor
        registry: StreamRegistry | None = request.app.state.stream_registry
        if sup is None:
            return []

        running = set(sup.running_cameras)
        out: list[CameraSourceView] = []
        for cfg in sup.cameras_with_config():
            cam_id = cfg["camera_id"]
            uri = str(cfg.get("source_uri", ""))
            kind = classify_source(uri)
            bcast = registry.get(cam_id) if registry is not None else None
            has_frames = bool(bcast and bcast.latest is not None)
            viewers = 1 if (bcast and bcast.has_subscribers) else 0
            out.append(
                CameraSourceView(
                    camera_id=cam_id,
                    source_uri=uri,
                    source_type=kind,
                    source_type_label=type_label(kind),
                    role=cfg.get("role"),
                    shed_id=cfg.get("shed_id"),
                    zone_id=cfg.get("zone_id"),
                    flock_id=cfg.get("flock_id"),
                    running=cam_id in running,
                    has_frames=has_frames,
                    viewer_count_hint=viewers,
                    stream_url=f"/api/cameras/{cam_id}/stream" if has_frames else None,
                )
            )
        return out

    return r


# ── Demo subsystem (Phase 3) ────────────────────────────────────────────────


def _build_demo_router() -> APIRouter:
    """`/api/demo/...` — list videos, start/stop, query status."""
    r = APIRouter()

    def _require_manager(request: Request) -> DemoManager:
        mgr: DemoManager | None = request.app.state.demo_manager
        if mgr is None:
            raise HTTPException(status_code=503, detail="Demo subsystem not configured")
        return mgr

    @r.get("/demo/videos", response_model=list[DemoVideoView])
    async def list_videos(request: Request) -> list[DemoVideoView]:
        mgr = _require_manager(request)
        return await mgr.list_videos()

    @r.get("/demo/images", response_model=list[DemoImageView])
    async def list_images(request: Request) -> list[DemoImageView]:
        mgr = _require_manager(request)
        return await mgr.list_images()

    @r.get("/demo/status", response_model=DemoStatusView)
    async def status(request: Request) -> DemoStatusView:
        mgr = _require_manager(request)
        return await mgr.status()

    @r.post("/demo/start", response_model=DemoStatusView)
    async def start(body: DemoStartRequest, request: Request) -> DemoStatusView:
        mgr = _require_manager(request)
        try:
            return await mgr.start(body.video)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @r.post("/demo/start-image", response_model=DemoStatusView)
    async def start_image(
        body: DemoStartImageRequest, request: Request
    ) -> DemoStatusView:
        mgr = _require_manager(request)
        try:
            return await mgr.start_image(body.image)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @r.post("/demo/stop", response_model=DemoStatusView)
    async def stop(request: Request) -> DemoStatusView:
        mgr = _require_manager(request)
        return await mgr.stop()

    @r.get("/demo/history", response_model=list[DemoRunView])
    async def history(
        request: Request, limit: int = Query(default=50, ge=1, le=200)
    ) -> list[DemoRunView]:
        mgr = _require_manager(request)
        # Manager exposes its underlying history store; if missing, return [].
        store = getattr(mgr, "_history", None)
        if store is None:
            return []
        runs = await store.list_runs(limit=limit)
        # DemoRun is a slots dataclass (no __dict__) — use asdict to serialize.
        from dataclasses import asdict  # noqa: PLC0415

        return [DemoRunView(**asdict(r)) for r in runs]

    return r


# ── Discovery (Phase 4) ────────────────────────────────────────────────────


def _build_discovery_router() -> APIRouter:
    """`/api/discover/{type}` — auto-discover cameras of the chosen type."""
    r = APIRouter()

    @r.get("/discover/types", response_model=list[str])
    async def types() -> list[str]:
        # Dropdown options for the Sources tab.
        return ["usb", "csi", "rtsp", "file"]

    @r.get("/discover/usb", response_model=list[DiscoveredDeviceView])
    async def usb_devices() -> list[DiscoveredDeviceView]:
        raw = await discover_usb()
        return [
            DiscoveredDeviceView(
                source_type="usb",
                name=d.get("name") or d.get("device", "USB camera"),
                device=d.get("device"),
                width=d.get("width"),
                height=d.get("height"),
                fps=d.get("fps"),
                suggested_source_uri=d.get("suggested_source_uri"),
            )
            for d in raw
        ]

    @r.get("/discover/csi", response_model=list[DiscoveredDeviceView])
    async def csi_devices() -> list[DiscoveredDeviceView]:
        raw = await discover_csi()
        return [
            DiscoveredDeviceView(
                source_type="csi",
                name=d.get("name", f"CSI sensor {d.get('sensor_id')}"),
                sensor_id=d.get("sensor_id"),
                width=d.get("width"),
                height=d.get("height"),
                fps=d.get("fps"),
                suggested_source_uri=d.get("suggested_source_uri"),
            )
            for d in raw
        ]

    @r.get("/discover/rtsp", response_model=list[DiscoveredDeviceView])
    async def rtsp_devices() -> list[DiscoveredDeviceView]:
        raw = await discover_rtsp()
        return [
            DiscoveredDeviceView(
                source_type="rtsp",
                name=d.get("name") or d.get("ip", "ONVIF camera"),
                ip=d.get("ip"),
                xaddr=d.get("xaddr"),
                requires_auth=d.get("requires_auth"),
                suggested_source_uri=d.get("suggested_source_uri"),
            )
            for d in raw
        ]

    @r.get("/discover/file", response_model=list[DiscoveredDeviceView])
    async def file_devices(request: Request) -> list[DiscoveredDeviceView]:
        videos_dir: Path | None = request.app.state.demo_videos_dir
        if videos_dir is None:
            return []
        raw = await discover_file(videos_dir)
        return [
            DiscoveredDeviceView(
                source_type="file",
                name=d["name"],
                size_bytes=d.get("size_bytes"),
                suggested_source_uri=d.get("suggested_source_uri"),
            )
            for d in raw
        ]

    return r


# ── Ad-hoc camera control (Phase 4) ────────────────────────────────────────


def _build_adhoc_router() -> APIRouter:
    """`/api/cameras/adhoc/{start,stop,status}` — one user-driven camera at a time."""
    r = APIRouter()

    def _require_manager(request: Request) -> AdhocManager:
        mgr: AdhocManager | None = request.app.state.adhoc_manager
        if mgr is None:
            raise HTTPException(status_code=503, detail="Ad-hoc camera subsystem not configured")
        return mgr

    @r.get("/cameras/adhoc/status", response_model=AdhocStatusView)
    async def status(request: Request) -> AdhocStatusView:
        return await _require_manager(request).status()

    @r.post("/cameras/adhoc/start", response_model=AdhocStatusView)
    async def start(body: AdhocStartRequest, request: Request) -> AdhocStatusView:
        mgr = _require_manager(request)
        try:
            return await mgr.start(
                source_type=body.source_type,
                source_uri=body.source_uri,
                label=body.label,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @r.post("/cameras/adhoc/stop", response_model=AdhocStatusView)
    async def stop(request: Request) -> AdhocStatusView:
        return await _require_manager(request).stop()

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
