# ADR 0001 — Modular Edge Architecture (Hexagonal + Outbox)

- **Status:** Accepted
- **Date:** 2026-05-10
- **Decision-makers:** Edge tech lead

## Context

We need an EdgeBox runtime that:
1. Ships PoC value within ~8 sprints.
2. Won't be thrown away when production scale, multi-tenancy, or new sensor types arrive.
3. Survives network partitions and power loss without losing data.
4. Can swap AI runtimes (ONNX → TensorRT → cloud-fallback) without rewrites.
5. Has a stable, reviewable contract with a separately-owned cloud team.

## Decision

We adopt a **hexagonal (ports & adapters) architecture** with a **durable outbox**
between event production and cloud sync, organized as long-running **pipelines**
inside a single `anyio` task group.

Concretely:
- Domain types are pure Pydantic dataclasses with no I/O imports.
- Each capability (frame capture, AI, sensors, sync, outbox) defines a port (`Protocol`)
  and one or more adapters.
- Pipelines compose ports → outbox; the sync pipeline drains outbox → cloud.
- Composition only happens in `main.py`.

## Alternatives considered

1. **Microservices on the edge** (separate processes for capture, inference, sync, sync over IPC).
   Rejected: too much operational overhead for a single-host PoC; we can split later by
   moving a module behind its existing port.
2. **Direct call from inference → cloud** (skip outbox).
   Rejected: any network hiccup loses data — unacceptable for a farm-floor device that
   may be offline for hours.
3. **Use a message broker on-device (NATS, RabbitMQ).**
   Rejected for PoC: SQLite is one less moving part with the same durability guarantees
   for our throughput. Easy to swap if we outgrow it.
4. **Two-language split (Go for sync, Python for AI).**
   Rejected: language boundary is a serialization tax with no current pay-off.
   Python end-to-end keeps the PoC team focused.

## Consequences

**Positive**
- PoC and production share the same code skeleton.
- Tests run without Docker (in-process simulator + tmp SQLite).
- Cloud team can mock against the contract before our code is feature-complete.
- Failure modes are well-defined (events durable until acked).

**Negative**
- More files than a quick-and-dirty script. The structure costs ~half a day to learn.
- Strict discipline needed to keep ports thin; contributors might be tempted to add
  new methods that leak adapter concerns.

## Related
- [docs/architecture.md](../architecture.md)
- [docs/contract.md](../contract.md)
