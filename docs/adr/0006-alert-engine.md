# ADR 0006 — Alert Engine via Outbox Wrapper

- **Status:** Accepted
- **Date:** 2026-05-11
- **Decision-makers:** Edge tech lead
- **Related:** [ADR 0001](0001-modular-edge-architecture.md), [ADR 0002](0002-config-driven-camera-supervision.md), [ADR 0005](0005-multi-model-inference-supervisor.md)

## Context

PoC Section 6.9 requires actionable alerts surfaced to the operator: camera
offline, sensor offline / out-of-range, weight below target, high huddling, edge
device offline. The edge has the raw signal for each (it produces or sees them
all in the outbox). What it lacks is the rule layer.

Three forces:
1. **No coupling**: alerting can't bleed into capture / inference / sync code.
   Those modules already do enough.
2. **No new infrastructure**: we have one outbox, one sync pipeline. Alerts
   should ride the same rails.
3. **Hot-pluggable rules**: adding a rule should be one file, no engine change.

## Decision

Introduce `edge.alerts` with three pieces:

1. **`AlertEngine`** — runs a list of `AlertRule`s. Each rule has two callbacks:
   - `on_event(event)` for event-driven rules (e.g. high huddling)
   - `tick(now)` for time-driven rules (e.g. camera offline)
   Per-rule exceptions are caught and logged; one bad rule can't break others.
2. **`AlertingOutbox(Outbox)`** — a decorator wrapping the underlying outbox.
   `put()` writes through first, then calls `engine.on_event(event)`. Pipelines
   are oblivious — they still see an `Outbox`.
3. **Built-in rules** in `edge.alerts.rules/`. Each is self-contained and
   uses the shared `RaisedTracker` for cooldown / dedup.

Alerts are themselves persisted to the same outbox (as `EventType.ALERT`) and
sync to the cloud through the existing `SyncPipeline` → `POST /v1/ingest/alerts`.
The engine filters its own events out of `on_event` to break the feedback loop.

## Why the wrapper pattern (vs an event bus)

Considered an explicit `EventBus` that pipelines publish to, with the outbox
and engine as subscribers. The wrapper achieves the same effect with **zero
churn to existing pipelines** — `FramePipeline`, `SensorPipeline`, etc. all
still take an `Outbox` Protocol parameter and call `outbox.put`. We can swap
the wrapper for a real bus later (e.g. when we add a metrics aggregator) by
adding subscribers behind the same `put()` call without API changes.

## Rule cooldowns

Each rule owns a `RaisedTracker(cooldown_seconds)`. When a rule wants to alert,
it checks `tracker.should_raise(correlation_key, now)`. If the condition
recovers, the rule calls `tracker.reset(key)` so the next breach alerts
immediately instead of waiting out the cooldown.

This produces sensible behavior:
- Sensor stuck out of range for an hour → 1 alert (cloud dedups extras anyway).
- Sensor flaps in and out → one alert per breach episode.
- Camera offline for a while, comes back, goes offline again → 2 alerts.

## Cloud-side responsibilities

The edge emits `open` alerts. Lifecycle (acknowledge / resolve / mark
false-positive) is **entirely** cloud-side per the requirements doc. Repeat
alerts share a `correlation_key` (`<rule_name>:<entity>`) so the cloud can
deduplicate, count, or merge as it sees fit.

## Alternatives considered

1. **Inline alert checks in each pipeline.** Rejected: spreads alerting logic
   across capture, inference, sensors; bad blast radius for changes.
2. **Server-side rule engine only.** Rejected: edge-local alerts close the loop
   faster (matter of seconds) and stay informative even during cloud outages —
   they queue in the outbox like everything else.
3. **Stream processing framework (Faust / similar).** Massive overkill for the
   half-dozen rules we need. A 50-line engine is fine.

## Consequences

**Positive**
- All four rules required for PoC Section 6.9 ship in Sprint 6 with isolated tests.
- Adding a new rule is a single file + one entry in `main.py`. No engine change.
- Edge alert behavior is unchanged when the cloud is offline — alerts queue.
- The wrapper is a thin pattern future subscribers can extend (metrics, anomaly
  detection, local logging) without touching pipelines.

**Negative**
- The engine sees every event the edge produces. At high event rates the
  per-rule loop has a cost. Benchmark when we have real footage; cap to ~10k
  events/sec/process today.
- Time-driven rules rely on `tick_interval_seconds` (default 10s). Alert latency
  for camera-offline is bounded by `threshold + tick_interval` (~70s default).
  Acceptable for PoC; tunable in config.

## Implementation pointers
- [src/edge/domain/alert.py](../../src/edge/domain/alert.py)
- [src/edge/alerts/engine.py](../../src/edge/alerts/engine.py)
- [src/edge/alerts/alerting_outbox.py](../../src/edge/alerts/alerting_outbox.py)
- [src/edge/alerts/rules/](../../src/edge/alerts/rules/)
- [src/edge/supervisors/alert_supervisor.py](../../src/edge/supervisors/alert_supervisor.py)
