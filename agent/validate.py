"""Validate data/conferences.json against data/schema.json (used in CI)."""
import sys

from common import load_data, validate_data

try:
    validate_data(load_data())
except Exception as exc:  # noqa: BLE001 - report any validation problem
    print(f"invalid conference data: {exc}", file=sys.stderr)
    sys.exit(1)
print("data/conferences.json is valid")
