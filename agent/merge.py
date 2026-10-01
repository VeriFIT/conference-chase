"""Merge agent results (out/*.json) into data/conferences.json.

Merge rules, per conference:
  * the edition is matched by year; a new year is appended;
  * a known value is never replaced by null, every non-null value overwrites;
  * rounds are matched by name (case-insensitive); new rounds are appended;
  * last_checked is updated for ok and not_found results (not for errors).
Prints a one-line summary, used as the commit message by the workflow.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import ROOT, load_data, save_data, today


def merge_fields(old: dict, new: dict, skip: tuple[str, ...] = ()) -> bool:
    changed = False
    for key, value in new.items():
        if key in skip or value is None:
            continue
        if old.get(key) != value:
            old[key] = value
            changed = True
    return changed


def merge_edition(conf: dict, new: dict, checked: str) -> bool:
    old = next((e for e in conf["editions"] if e["year"] == new["year"]), None)
    if old is None:
        conf["editions"].append({**new, "last_checked": checked})
        return True
    changed = merge_fields(old, new, skip=("rounds", "last_checked"))
    by_name = {r["name"].strip().lower(): r for r in old["rounds"]}
    for rnd in new.get("rounds", []):
        match = by_name.get(rnd["name"].strip().lower())
        if match is None:
            old["rounds"].append(rnd)
            changed = True
        else:
            changed |= merge_fields(match, rnd, skip=("name",))
    old["last_checked"] = checked
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "out", help="directory with <id>.json files")
    args = parser.parse_args()

    data = load_data()
    by_id = {c["id"]: c for c in data["conferences"]}
    updated, unchanged, failed = [], [], []

    for path in sorted(args.results.glob("**/*.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        conf = by_id.get(result.get("id"))
        if conf is None:
            print(f"skipping {path}: unknown conference id", file=sys.stderr)
            continue
        status = result.get("status")
        if status == "error":
            failed.append(conf["id"])
            print(f"{conf['id']}: agent error: {result.get('error')}", file=sys.stderr)
            continue
        checked = result.get("checked") or today().isoformat()
        conf["last_checked"] = checked
        if status == "ok" and merge_edition(conf, result["edition"], checked):
            updated.append(conf["acronym"])
        else:
            unchanged.append(conf["id"])

    data["updated"] = today().isoformat()
    save_data(data)

    summary = f"Update conference data ({len(updated)} updated"
    summary += f": {', '.join(updated)}" if updated else ""
    summary += f"; {len(unchanged)} unchanged; {len(failed)} failed)"
    print(summary)


if __name__ == "__main__":
    main()
