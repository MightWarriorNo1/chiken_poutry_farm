# Edge ↔ Cloud Contract

This folder is the **shared truth** between the EdgeBox runtime (this repo) and the
Prosper Cloud Backend (separate repo). Anything not defined here is not part of the
contract and is subject to change without notice.

## Files

| File | Purpose |
|---|---|
| [openapi.yaml](openapi.yaml) | OpenAPI 3.1 spec — endpoints, parameters, auth, response codes. |
| [events/](events/) | JSON Schema 2020-12 — canonical wire format for each event type. |

## Versioning policy

| Change | Bump |
|---|---|
| Add an optional field | Patch (e.g. `0.1.0` → `0.1.1`) |
| Add an enum value | Patch — consumers must tolerate unknown values |
| Make an optional field required, remove a field, or change a type | **Breaking — bump the path** (`/v1/` → `/v2/`). Edge supports both during migration. |

Every payload carries a `schema_version` field for fine-grained tracking inside a path version.

## How to evolve

1. Open a PR that updates `openapi.yaml` **and** the affected `events/*.schema.json`.
2. Bump `info.version` in `openapi.yaml` and the `schema_version` examples.
3. Tag both teams in the PR — API team must approve before merge.
4. Generate clients (see [docs/contract.md](../docs/contract.md)).
5. Land the PR; both repos pin to the new version.

## Mock server for development

Point `EDGE_CLOUD_BASE_URL` at a Prism mock until the real API is online:

```powershell
docker run --rm -p 4010:4010 -v ${PWD}/contracts:/tmp \
  stoplight/prism:5 mock -h 0.0.0.0 /tmp/openapi.yaml
```

Then set `EDGE_CLOUD_BASE_URL=http://localhost:4010` in `.env`.
