"""submit_manual_weight CLI writes a valid envelope to the outbox."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from edge.domain.events import EventEnvelope, EventType
from edge.domain.manual_weight import ManualWeightSample
from edge.outbox.sqlite_outbox import SqliteOutbox


@pytest.mark.asyncio
async def test_envelope_round_trips_through_outbox(tmp_path: Path) -> None:
    """Smoke test mirroring what the CLI does end-to-end."""
    outbox_path = tmp_path / "ob.db"
    sample = ManualWeightSample(
        device_id="edge-test",
        flock_id="flock-A",
        shed_id="shed-1",
        sampled_at=datetime.now(timezone.utc),
        flock_age_days=28,
        sample_count=50,
        average_weight_g=1620.0,
        operator="tester",
    )
    envelope = EventEnvelope(
        event_type=EventType.MANUAL_WEIGHT_SAMPLE,
        payload=sample.model_dump(mode="json"),
    )

    outbox = SqliteOutbox(outbox_path)
    await outbox.init()
    try:
        await outbox.put(envelope)
        # Reopen — proves persistence across process restarts.
    finally:
        await outbox.close()

    outbox2 = SqliteOutbox(outbox_path)
    await outbox2.init()
    try:
        events = await outbox2.peek(EventType.MANUAL_WEIGHT_SAMPLE, 10)
        assert len(events) == 1
        payload = events[0].payload
        assert payload["flock_id"] == "flock-A"
        assert payload["average_weight_g"] == 1620.0
        assert payload["operator"] == "tester"
        assert payload["sample_count"] == 50
    finally:
        await outbox2.close()
