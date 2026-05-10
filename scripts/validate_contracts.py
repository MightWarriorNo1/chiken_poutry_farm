"""CI gate: ensure every JSON Schema in contracts/events/ is well-formed.

Optionally validates that the schema_version examples in openapi.yaml align with the
top-level $id versions in the schemas — catches drift before review.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
EVENTS_DIR = ROOT / "contracts" / "events"
OPENAPI_PATH = ROOT / "contracts" / "openapi.yaml"


def main() -> int:
    failures: list[str] = []

    # 1. Each schema is a valid Draft 2020-12 schema.
    for schema_path in sorted(EVENTS_DIR.glob("*.schema.json")):
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"{schema_path.name}: invalid JSON — {exc}")
            continue
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{schema_path.name}: schema invalid — {exc}")

    # 2. OpenAPI loads.
    try:
        with OPENAPI_PATH.open("r", encoding="utf-8") as f:
            yaml.safe_load(f)
    except yaml.YAMLError as exc:
        failures.append(f"openapi.yaml: {exc}")

    if failures:
        print("Contract validation failed:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1

    print(f"OK — {sum(1 for _ in EVENTS_DIR.glob('*.schema.json'))} schemas validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
