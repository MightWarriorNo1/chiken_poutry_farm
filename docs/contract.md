# Edge ↔ Cloud Contract Guide

This guide explains how to read, change, and consume the contract published in
[contracts/](../contracts/).

## What's in scope

- **Wire format**: every byte that flows between the edge and the cloud.
- **Endpoints**: HTTP method, path, status codes, batching rules.
- **Auth**: device JWT today; mTLS upgrade is forward-compatible.

## What's out of scope

- Internal cloud topology (queues, databases, microservice splits).
- Internal edge structure (pipelines, models — see [architecture.md](architecture.md)).
- The web dashboard's API (which is between web and cloud, not edge and cloud).

## Generating clients

The OpenAPI spec is the source of truth. Both teams generate idiomatic clients:

| Team | Tool |
|---|---|
| Edge (Python) — only used in tests | `openapi-python-client generate --path contracts/openapi.yaml` |
| API (server stub validation) | `prism mock contracts/openapi.yaml` for dev; `openapi-generator` for client tests |
| Web (TS) — for any direct hits | `openapi-typescript contracts/openapi.yaml -o web/src/api.ts` |

## Versioning rules

| Change | Bump | Action required |
|---|---|---|
| Add an optional field | Patch | Both sides tolerate via `additionalProperties: false` discipline. |
| Add an enum value | Patch | Consumers must accept unknown enums (forward-compat). |
| Add an endpoint | Minor | New tag in OpenAPI; existing endpoints unchanged. |
| Make optional → required, remove a field, change type | **Major** | Bump path (`/v1` → `/v2`). Edge supports both during migration. |

`schema_version` inside payloads is informational; the path version is the
source of truth.

## Coordination flow

1. PR opened against `contracts/` with the schema change + bumped version.
2. Both teams' tech leads review in the same PR.
3. Mock server (Prism) is regenerated; both repos update their pinned version.
4. Each side adapts in parallel, meeting at integration test.

## Field semantics worth fixing now

| Field | Meaning |
|---|---|
| `event_id` | Edge-generated UUID. Cloud uses it for idempotency (deduplication). |
| `captured_at` | Wall-clock time of frame/sensor read at the edge (UTC). |
| `processed_at` | Wall-clock time AI finished processing (UTC). Latency = processed − captured. |
| `recorded_at` (sensor) | Sensor's own timestamp if available, else edge wall-clock. |
| `model_version` | `<name>@<semver>` — must match a `metadata.json` in [models/](../models/). |
| `confidence` | [0, 1]; what the model thinks about *its own* output. Different per model. |
| `density_score` | [0, 1]; saturating curve over birds-per-megapixel. Tuned per camera. |
| `huddling_score` | [0, 1]; fraction of birds in tight DBSCAN clusters. |
| `snapshot_uri` | Object-storage URI from the presigned-upload flow. Cloud may proxy or CDN it. |

## Idempotency

Cloud must treat repeat ingestion of the same `event_id` as a no-op (200 OK,
`accepted: 0`). The edge **will** retransmit on its retry path; the contract
guarantees this is safe.
