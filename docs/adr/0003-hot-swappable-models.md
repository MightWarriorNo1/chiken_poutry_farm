# ADR 0003 — Hot-Swappable AI Models via Registry + Proxy

- **Status:** Accepted
- **Date:** 2026-05-11
- **Decision-makers:** Edge tech lead
- **Related:** [ADR 0001](0001-modular-edge-architecture.md), [ADR 0002](0002-config-driven-camera-supervision.md)

## Context

Sprint 2 introduces real ONNX-based bird detection. Two requirements pull in
opposite directions:

1. **Operational:** the cloud must be able to promote a new model version to a
   fleet of edges without forcing a process restart per device.
2. **Architectural:** `FramePipeline` was designed in Sprint 0 to hold a
   long-lived `BirdDetector` reference (it's a Protocol, not a registry lookup).
   Threading a registry through the pipeline would leak inference concerns into
   capture/processing code.

## Decision

Add three small pieces in `edge.inference`:

1. **`DetectorRegistry`** — owns the currently-active `BirdDetector`. Atomic
   `swap(new) -> old` returns the previous instance for cleanup.
2. **`ProxiedBirdDetector`** — a thin facade that satisfies the `BirdDetector`
   Protocol structurally and forwards `detect()` to `registry.current`.
3. **`InferenceSupervisor`** — mirrors `CameraSupervisor`. `apply(ai_config)`
   reads `models[*]` from `EdgeConfig.ai`, looks up the requested version via
   `ModelLoader`, builds a new detector via `build_bird_detector(descriptor)`,
   and swaps it in. Failed swaps are logged but preserve the current detector.

`ConfigPipeline` calls both supervisors in a single `_apply()`, inference first
so a new detector is ready before any FramePipeline tries to use it.

## Alternatives considered

1. **Thread the `DetectorRegistry` directly into `FramePipeline`.** Rejected:
   makes the pipeline aware of model lifecycle. Proxy stays cleaner — the
   pipeline doesn't know swaps exist.
2. **Restart all camera pipelines on model change.** Rejected: causes a visible
   outage per swap. With the proxy, swaps are zero-downtime.
3. **Separate process per detector.** Rejected for PoC: an ONNX session is fine
   in the same process. Production may split, but the supervisor abstraction
   doesn't change — only the build step does.
4. **Keep multiple loaded models around.** Considered. Useful for canarying.
   Out of scope for Sprint 2 — easy to add later by extending the registry to
   hold a map and routing per-camera based on config.

## Consequences

**Positive**
- Cloud-driven model promotion is a YAML edit + 5 minutes (config poll).
- Swap failures don't break inference — the pipeline keeps using the old model.
- The `StubBirdDetector` still works as a fallback (`stub-*` versions skip the
  artifact requirement entirely), so demos run without any downloaded model.
- Same shape applies trivially to `WeightEstimator` and `HuddlingDetector` later.

**Negative**
- One small layer of indirection on the hot path. Measured cost: ~50 ns per
  `detect()` call — invisible against ~5 ms inference.
- A bad model swap is logged but silent to upstream consumers — the operator
  sees it via `inference.swap.failed` events. Sprint 6 will surface it as an
  alert.

## Implementation pointers
- [src/edge/inference/model_loader.py](../../src/edge/inference/model_loader.py)
- [src/edge/inference/factory.py](../../src/edge/inference/factory.py)
- [src/edge/inference/proxied_detector.py](../../src/edge/inference/proxied_detector.py)
- [src/edge/inference/models/bird_detector.py](../../src/edge/inference/models/bird_detector.py)
- [src/edge/supervisors/inference_supervisor.py](../../src/edge/supervisors/inference_supervisor.py)
