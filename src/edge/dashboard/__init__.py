"""On-device dashboard.

Read-only view of edge state — a local projection of every event the pipelines
emit, served as JSON + a React UI on `127.0.0.1`. Lives entirely on the edge box;
the cloud dashboard is a separate repo.

See [docs/adr/0007-local-dashboard.md] for design rationale.
"""
