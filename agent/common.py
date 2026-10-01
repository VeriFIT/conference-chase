"""Shared helpers for loading, validating and saving the conference data."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "conferences.json"
SCHEMA_FILE = ROOT / "data" / "schema.json"


def today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def load_schema() -> dict:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def edition_schema() -> dict:
    """Schema for a single edition, with $defs inlined so it validates standalone."""
    schema = load_schema()
    return {"$defs": schema["$defs"], "$ref": "#/$defs/edition"}


def load_data(path: Path = DATA_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_data(data: dict) -> None:
    jsonschema.validate(data, load_schema())
    ids = [c["id"] for c in data["conferences"]]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate conference ids: {sorted(dupes)}")
    unknown = {c["category"] for c in data["conferences"]} - set(data["categories"])
    if unknown:
        raise ValueError(f"conferences use undeclared categories: {sorted(unknown)}")


def save_data(data: dict, path: Path = DATA_FILE) -> None:
    validate_data(data)
    data["conferences"].sort(key=lambda c: c["id"])
    for conf in data["conferences"]:
        conf["editions"].sort(key=lambda e: e["year"])
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_day(value: str | None) -> dt.date | None:
    """Date part of an ISO date or date-time string."""
    if not value:
        return None
    return dt.date.fromisoformat(value[:10])
