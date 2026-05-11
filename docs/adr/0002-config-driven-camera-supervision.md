# ADR 0002 — Config-Driven Camera Supervision

- **Status:** Accepted
- **Date:** 2026-05-11
- **Decision-makers:** Edge tech lead
- **Supersedes:** None
- **Related:** [ADR 0001](0001-modular-edge-architecture.md)

## Context

Cameras come and go on a poultry farm — sheds get re-cabled, models change focal
length, RTSP URLs rotate. A v1 cloud will issue an `EdgeConfig` to each device
listing its desired cameras and sensors. The edge must apply this dynamically,
not on cold-restart only.

Open questions Sprint 0 left:
1. How does the edge learn which cameras to run?
2. What's the lifecycle of a camera pipeline?
3. How do we develop offline (without a cloud at all)?

## Decision

Adopt a **Kubernetes-style reconciliation pattern**:

1. **`EdgeConfigSource`** port — `async fetch() -> dict | None`. Two adapters:
   - `HttpConfigSource` (polls cloud with ETag)
   - `YamlConfigSource` (file on disk, mtime-detected reload)
2. **`ConfigPipeline`** polls the source on a schedule and pushes desired state
   into the supervisor.
3. **`CameraSupervisor`** owns a dict of `camera_id → CancelScope`. `apply(desired)`
   is idempotent:
   - Cameras in `desired` that aren't running → start.
   - Running cameras absent from `desired` → cancel.
   - Running cameras whose config differs → cancel + start fresh.
4. Each camera pipeline runs as a child of the main task group, so structured
   concurrency guarantees still apply (one fatal error tears the edge down).

## Alternatives considered

1. **Static config at startup.** Rejected: requires SSHing into the device to add
   a camera; doesn't scale to farms or fleets.
2. **Cloud pushes config via webhook.** Rejected for PoC: requires inbound
   connectivity to the edge, which a typical farm NAT won't allow. ETag polling is
   ~1 HTTP call per 5 min and trivially supports the same semantics.
3. **Threads per camera.** Rejected: `anyio` task groups give us cancellation +
   error propagation for free, without GIL contention or extra synchronization.

## Consequences

**Positive**
- Offline development is real: edit `example.config.yaml`, save, watch cameras
  reshape — no cloud required.
- Cloud-driven and file-driven configs are wire-compatible (same `EdgeConfig`
  schema), so promoting from dev to prod is a one-line env var swap.
- Sprint 1 demo: full path from config → camera → outbox → cloud mock, with
  stubbed AI. Lets the API team integrate against real events while we build
  real models in Sprint 2+.
- The reconciler pattern is well-understood; new contributors recognize it from
  Kubernetes / systemd / etc.

**Negative**
- One more abstraction (`EdgeConfigSource`, `CameraSupervisor`) — costs some
  ramp-up. Mitigated by tests that exercise the full pattern.
- Config polling lag: a camera change takes up to `config_poll_interval_seconds`
  to apply. Acceptable for PoC; can add a push-channel later without breaking the
  port contract.

## Implementation notes
- See [src/edge/supervisors/camera_supervisor.py](../../src/edge/supervisors/camera_supervisor.py),
  [src/edge/pipelines/config_pipeline.py](../../src/edge/pipelines/config_pipeline.py),
  and [src/edge/config_sources/](../../src/edge/config_sources/).
- Reconciliation is serialized via an `anyio.Lock` to keep `apply()` calls atomic.
- Each camera pipeline gets its own `anyio.CancelScope`, allowing surgical stops
  without disturbing siblings.
