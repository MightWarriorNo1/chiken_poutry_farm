"""Submit a manual weight sample to the local outbox.

The next sync cycle picks it up and POSTs it to the cloud at
`/v1/ingest/manual-weights`. The outbox is SQLite-WAL so this CLI is safe to
run while `prosper-edge` is also running.

Usage:
    python scripts/submit_manual_weight.py \\
        --flock flock-A --shed shed-1 --age 28 \\
        --count 50 --avg 1620 --min 1480 --max 1780 \\
        --operator "Maria S."
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import anyio


async def amain(args: argparse.Namespace) -> int:
    # Imports here so --help works without project deps installed.
    from edge.config import load_settings  # noqa: PLC0415
    from edge.domain.events import EventEnvelope, EventType  # noqa: PLC0415
    from edge.domain.manual_weight import ManualWeightSample  # noqa: PLC0415
    from edge.outbox.sqlite_outbox import SqliteOutbox  # noqa: PLC0415

    settings = load_settings()
    outbox_path = Path(args.outbox or settings.storage.outbox_path)
    device_id = args.device or settings.device_id

    sample = ManualWeightSample(
        device_id=device_id,
        flock_id=args.flock,
        shed_id=args.shed,
        sampled_at=args.sampled_at,
        flock_age_days=args.age,
        sample_count=args.count,
        average_weight_g=args.avg,
        min_weight_g=args.min,
        max_weight_g=args.max,
        notes=args.notes,
        operator=args.operator,
    )

    envelope = EventEnvelope(
        event_type=EventType.MANUAL_WEIGHT_SAMPLE,
        payload=sample.model_dump(mode="json"),
    )

    outbox = SqliteOutbox(outbox_path)
    await outbox.init()
    try:
        await outbox.put(envelope)
        print(
            f"✓ Queued manual weight sample {sample.event_id} "
            f"for flock={sample.flock_id} age={sample.flock_age_days}d "
            f"avg={sample.average_weight_g}g (outbox: {outbox_path})"
        )
    finally:
        await outbox.close()
    return 0


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--flock", required=True, help="Flock id (must match flock_id on the camera).")
    p.add_argument("--shed", help="Shed id (optional).")
    p.add_argument("--age", type=int, help="Flock age in days (optional but recommended).")
    p.add_argument("--count", type=int, required=True, help="Number of birds in the sample.")
    p.add_argument("--avg", type=float, required=True, help="Average weight (grams).")
    p.add_argument("--min", type=float, help="Min weight (grams).")
    p.add_argument("--max", type=float, help="Max weight (grams).")
    p.add_argument("--notes", help="Free-form notes.")
    p.add_argument("--operator", help="Person who took the sample.")
    p.add_argument(
        "--sampled-at",
        type=_parse_iso,
        default=datetime.now(timezone.utc),
        help="When the sample was taken (ISO-8601). Defaults to now.",
    )
    p.add_argument("--device", help="Override device_id (defaults to settings).")
    p.add_argument("--outbox", help="Override outbox path (defaults to settings).")
    args = p.parse_args()

    try:
        return anyio.run(amain, args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
