# ADR 0005 — Multi-Model Inference Supervisor

- **Status:** Accepted
- **Date:** 2026-05-11
- **Decision-makers:** Edge tech lead
- **Supersedes / refines:** [ADR 0003](0003-hot-swappable-models.md)
- **Related:** [ADR 0001](0001-modular-edge-architecture.md), [ADR 0002](0002-config-driven-camera-supervision.md)

## Context

Sprint 2 introduced `InferenceSupervisor` as a single-model reconciler (bird
detector only). Sprint 4 adds a weight estimator; Sprint 5 will add a huddling
detector. Three near-identical supervisors would be embarrassing.

Each model still needs its own port (`detect` vs `estimate` vs `score`) — they
can't share a generic interface. But the **lifecycle** is identical: parse
`EdgeConfig.ai.models`, build via factory, optionally `start()`, install into
the right registry, swap atomically, isolate failures.

## Decision

Generalize `InferenceSupervisor` to dispatch by **model name** using a
**handlers map**:

```python
inference_sup = InferenceSupervisor(
    loader=ModelLoader(...),
    handlers={
        "bird-detector":   ModelHandler(build=build_bird_detector,   install=detector_registry.swap),
        "weight-estimator": ModelHandler(build=build_weight_estimator, install=estimator_registry.swap),
        # huddling-detector lands in Sprint 5 — one line addition.
    },
)
```

`ModelHandler` is a tiny frozen dataclass holding two callables (`build` and
`install`). The supervisor only knows about names and versions; it never touches
the actual detector/estimator objects beyond calling `getattr(obj, "start")` if
present.

Per-model state (current version, last swap success/failure) is keyed by name in
a single dict, so:
- Idempotency works per-model (only swap the ones that changed).
- A failure on one model can't disturb the others (each install is its own
  try/except).
- A new model name is **one factory + one handler entry** — no supervisor change.

## Alternatives considered

1. **Three sibling supervisors (`Bird*`, `Weight*`, `Huddling*`).** Rejected:
   triplication of the same loop; clutters `main.py`.
2. **Generic `Registry[T]`/`Proxy[T]` via Python generics.** Considered. The
   registry is trivially generic, but the proxy can't be (it has to dispatch to
   the right method name). Kept registries small per port and let the supervisor
   carry the generality.
3. **Subscribe to a model-changed event bus.** Over-engineered for one publisher
   (the config pipeline) and N subscribers (the supervisors). The dict-of-handlers
   keeps the topology obvious.

## Consequences

**Positive**
- Adding a new model port = **one factory + one handler entry**.
- Failure isolation reads cleanly in logs: `inference.swap.failed model=bird-detector`.
- `versions()` snapshot is now a useful operational signal — show it on the
  device heartbeat in Sprint 6.

**Negative**
- Slightly more indirection — readers have to follow the handler entry to find
  the actual factory. Mitigated by keeping `factory.py` and `main.py` adjacent
  in cognitive distance.
- The `ModelHandler.install` callable is loosely typed (`Callable[[Any], Any]`).
  Tightening it requires `TypeVar`s on `ModelHandler` and a separate handler
  type per port. Not worth it yet; the call site (`main.py`) makes the types
  obvious.

## Manual weight ingestion (related Sprint 4 work)

Independently, Sprint 4 adds `EventType.MANUAL_WEIGHT_SAMPLE` and a CLI
(`scripts/submit_manual_weight.py`) that writes one envelope to the outbox.
SyncPipeline picks it up like any other event and POSTs to
`/v1/ingest/manual-weights` (new endpoint in [contracts/openapi.yaml](../../contracts/openapi.yaml)).

This closes the AI ↔ ground-truth loop the heuristic acknowledges it can't
provide on its own. v1.0.0 of the estimator will be trained on the pairs
produced here.

## Implementation pointers
- [src/edge/supervisors/inference_supervisor.py](../../src/edge/supervisors/inference_supervisor.py)
- [src/edge/inference/factory.py](../../src/edge/inference/factory.py)
- [src/edge/inference/proxied_estimator.py](../../src/edge/inference/proxied_estimator.py)
- [src/edge/inference/models/weight_estimator.py](../../src/edge/inference/models/weight_estimator.py)
- [src/edge/domain/manual_weight.py](../../src/edge/domain/manual_weight.py)
- [scripts/submit_manual_weight.py](../../scripts/submit_manual_weight.py)
