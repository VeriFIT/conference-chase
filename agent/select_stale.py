"""Print a JSON array of conference ids that should be refreshed, stalest first.

A conference is stale when it has no upcoming submission deadline, when its
upcoming edition still has unknown dates or low confidence, or when it has not
been checked for RECHECK_DAYS. Conferences checked within MIN_GAP_DAYS are
skipped so a single unresolvable conference cannot hog every weekly run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json

from common import load_data, parse_day, today

RECHECK_DAYS = 30
MIN_GAP_DAYS = 6


def upcoming_edition(conf: dict, now: dt.date) -> dict | None:
    for edition in sorted(conf["editions"], key=lambda e: e["year"]):
        for rnd in edition["rounds"]:
            day = parse_day(rnd.get("submission_deadline"))
            if day and day >= now:
                return edition
    return None


def staleness(conf: dict, now: dt.date) -> str | None:
    """Reason why the conference needs a refresh, or None if it is fresh."""
    last = parse_day(conf.get("last_checked"))
    if last and (now - last).days < MIN_GAP_DAYS:
        return None
    edition = upcoming_edition(conf, now)
    if edition is None:
        return "no upcoming deadline"
    if edition.get("confidence") == "low":
        return "low confidence"
    for rnd in edition["rounds"]:
        if not rnd.get("notification") or not rnd.get("final_version"):
            return "incomplete dates"
    if not edition.get("cfp") and not any(r.get("cfp") for r in edition["rounds"]):
        return "missing CFP link"
    if last is None or (now - last).days >= RECHECK_DAYS:
        return "periodic recheck"
    return None


def select(data: dict, limit: int, now: dt.date) -> list[str]:
    stale = [c for c in data["conferences"] if staleness(c, now)]
    # Never-checked first, then oldest check.
    stale.sort(key=lambda c: (c.get("last_checked") or "", c["id"]))
    return [c["id"] for c in stale[:limit]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max", type=int, default=10, help="maximum number of conferences")
    parser.add_argument("--ids", default="", help="comma-separated ids; overrides selection")
    parser.add_argument("--explain", action="store_true", help="print reasons to stderr")
    args = parser.parse_args()

    data = load_data()
    known = {c["id"] for c in data["conferences"]}
    if args.ids.strip():
        ids = [i.strip() for i in args.ids.split(",") if i.strip()]
        missing = [i for i in ids if i not in known]
        if missing:
            raise SystemExit(f"unknown conference ids: {missing}")
    else:
        ids = select(data, args.max, today())

    if args.explain:
        import sys
        now = today()
        by_id = {c["id"]: c for c in data["conferences"]}
        for i in ids:
            print(f"{i}: {staleness(by_id[i], now) or 'requested'}", file=sys.stderr)
    print(json.dumps(ids))


if __name__ == "__main__":
    main()
