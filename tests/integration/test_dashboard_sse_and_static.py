"""Dashboard live feed (SSE) + static asset serving.

Phase 4 coverage: events flowing through ProjectingOutbox reach `/events`
subscribers, and the React `dist/` build is served correctly when present.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import anyio
import httpx
import pytest

from edge.config import DashboardSettings
from edge.dashboard.event_bus import EventBus
from edge.dashboard.projecting_outbox import ProjectingOutbox
from edge.dashboard.server import create_app
from edge.dashboard.sqlite_read_model import SqliteReadModel
from edge.domain.events import EventEnvelope, EventType


class _NullInner:
    async def init(self): ...
    async def close(self): ...
    async def put(self, _ev): ...
    async def peek(self, *_): return []
    async def ack(self, _): ...
    async def nack(self, _): ...
    async def pending_count(self): return 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sse_route_is_registered(tmp_path: Path) -> None:
    """The SSE handler is an infinite-stream endpoint, which is awkward to
    exercise through httpx's ASGI transport (the stream context manager waits
    for the response to close, and SSE responses never close cleanly through
    that transport). We instead assert the route is registered.

    End-to-end SSE behavior is exercised in two cheaper places:
      - `tests/unit/test_event_bus.py` covers the bus that drives the stream.
      - `test_eventbus_publishes_what_outbox_writes` below covers the
        ProjectingOutbox → EventBus tee.
    """
    rm = SqliteReadModel(tmp_path / "view.db")
    await rm.init()
    try:
        app = create_app(
            read_model=rm,
            event_bus=EventBus(),
            settings=DashboardSettings(),
        )
        paths = {route.path for route in app.routes}  # type: ignore[attr-defined]
        assert "/events" in paths
    finally:
        await rm.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_eventbus_publishes_what_outbox_writes(tmp_path: Path) -> None:
    """Direct verification that the ProjectingOutbox tees into the EventBus —
    no HTTP layer, no streaming buffer surprises."""
    rm = SqliteReadModel(tmp_path / "view.db")
    await rm.init()
    bus = EventBus()
    outbox = ProjectingOutbox(inner=_NullInner(), read_model=rm, event_bus=bus)

    try:
        received: list[EventEnvelope] = []
        async with bus.subscribe() as recv:
            env = EventEnvelope(
                event_type=EventType.BIRD_DETECTION,
                payload={
                    "camera_id": "cam-X",
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "bird_count": 10,
                    "density_score": 0.1,
                    "confidence": 0.9,
                },
            )
            await outbox.put(env)
            with anyio.fail_after(2.0):
                received.append(await recv.receive())

        assert len(received) == 1
        assert received[0].event_type == EventType.BIRD_DETECTION
        assert received[0].payload["camera_id"] == "cam-X"
    finally:
        await rm.close()


# Keep `anyio` and `EventType` imported even if linter doesn't see use through
# the bus/publish paths above.
_ = anyio
_ = EventType


@pytest.mark.integration
@pytest.mark.asyncio
async def test_static_dist_served_when_present(tmp_path: Path) -> None:
    """When a `dist/` is wired in, root returns index.html and /assets/* works."""
    rm = SqliteReadModel(tmp_path / "view.db")
    await rm.init()
    static_dir = tmp_path / "dist"
    (static_dir / "assets").mkdir(parents=True)
    (static_dir / "index.html").write_text(
        '<!doctype html><html><body><div id="root"></div>'
        '<script src="/assets/main.js"></script></body></html>'
    )
    (static_dir / "assets" / "main.js").write_text("console.log('hi')")
    app = create_app(
        read_model=rm,
        event_bus=EventBus(),
        settings=DashboardSettings(),
        static_dir=static_dir,
    )

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            root = await client.get("/")
            asset = await client.get("/assets/main.js")
            # SPA fallback: a deep route returns index.html, not 404.
            deep = await client.get("/sensors/temp-1")
            api = await client.get("/api/status")

        assert root.status_code == 200
        assert b"<div id=\"root\">" in root.content

        assert asset.status_code == 200
        assert b"console.log" in asset.content

        assert deep.status_code == 200
        assert b"<div id=\"root\">" in deep.content

        assert api.status_code == 200  # still reachable
    finally:
        await rm.close()
