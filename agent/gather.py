"""Run the LLM agent for a single conference and write out/<id>.json.

The output file always exists after a run (status ok / not_found / error), so
one failing conference never breaks the weekly workflow.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

import jsonschema

from common import ROOT, edition_schema, load_data, today
from llm import make_client
from tools import TOOL_SPECS, TOOLS

MAX_STEPS = 15
OUT_DIR = ROOT / "out"

_NULL_STR = {"type": ["string", "null"]}
SUBMIT_SPEC = {
    "type": "function",
    "function": {
        "name": "submit_result",
        "description": (
            "Submit the final answer. Call exactly once. Set found=false if no reliable "
            "information about an upcoming edition could be found."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "found": {"type": "boolean"},
                "edition": {
                    "type": ["object", "null"],
                    "properties": {
                        "year": {"type": "integer"},
                        "link": {**_NULL_STR, "description": "Official edition website"},
                        "cfp": {**_NULL_STR, "description": "URL of the call for papers page (main research track)"},
                        "location": {**_NULL_STR, "description": "City, Country"},
                        "conference_start": {**_NULL_STR, "description": "YYYY-MM-DD"},
                        "conference_end": {**_NULL_STR, "description": "YYYY-MM-DD"},
                        "pc_chairs": {
                            "type": ["array", "null"],
                            "description": "Program committee chairs of the main track (null if not stated)",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "affiliation": {**_NULL_STR, "description": "e.g. 'TU Wien, Austria'"},
                                },
                                "required": ["name"],
                            },
                        },
                        "rounds": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string", "description": "e.g. 'Main', 'Round 1', 'Fall'"},
                                    "abstract_deadline": {**_NULL_STR, "description": "YYYY-MM-DD or YYYY-MM-DDTHH:MM"},
                                    "submission_deadline": {**_NULL_STR, "description": "YYYY-MM-DD or YYYY-MM-DDTHH:MM"},
                                    "timezone": {**_NULL_STR, "description": "AoE, UTC, or UTC+H / UTC-H"},
                                    "rebuttal_start": {**_NULL_STR, "description": "author response period start, YYYY-MM-DD"},
                                    "rebuttal_end": {**_NULL_STR, "description": "author response period end, YYYY-MM-DD"},
                                    "notification": {**_NULL_STR, "description": "YYYY-MM-DD"},
                                    "final_version": {**_NULL_STR, "description": "camera-ready, YYYY-MM-DD"},
                                    "cfp": {**_NULL_STR, "description": "only if this round has its own CFP page"},
                                    "submission_link": {**_NULL_STR, "description": "submission system URL (HotCRP, EasyChair, ...)"},
                                    "page_limit": {**_NULL_STR, "description": "e.g. '16 pages LNCS excl. references'"},
                                    "notes": {**_NULL_STR, "description": "short remark, e.g. 'abstract mandatory'"},
                                },
                                "required": ["name"],
                            },
                        },
                        "source": {**_NULL_STR, "description": "URL where the dates were found"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "notes": {**_NULL_STR, "description": "Short remark, e.g. 'dates tentative'"},
                    },
                    "required": ["year", "rounds", "source", "confidence"],
                },
            },
            "required": ["found"],
        },
    },
}

SYSTEM_PROMPT = """You are a careful research assistant that tracks deadlines of scientific conferences.
Today is {today}. Your task: find the NEXT edition of the given conference whose paper submission
deadline is upcoming (or, if none is announced yet, the most recently announced edition) and
extract its important dates.

Rules:
- Use web_search and fetch_url. Prefer the official conference website / call for papers over
  aggregators (WikiCFP, conference-index sites); use aggregators only to locate the official page.
- Never guess or extrapolate dates from previous years. Use null for anything not stated.
- If the conference has several submission rounds/cycles, report each as a separate round.
  A single-cycle conference has one round named "Main". Do not list workshops, tool papers or
  artifact evaluation as rounds unless they are the main paper track's cycles.
- Find the official call for papers page and report its URL as `cfp` (null if there is none).
  For each round also report, when stated: the author response / rebuttal period, the
  submission system link, and the page limit of regular papers.
- Report the program committee (PC) chairs of the main track as `pc_chairs`, with their
  affiliations as listed on the official site (null if not announced). Do not include
  general chairs, steering committee or track chairs of other tracks.
- Dates: YYYY-MM-DD; deadlines may include a time as YYYY-MM-DDTHH:MM. Timezone is "AoE"
  for Anywhere on Earth, otherwise "UTC" or "UTC+H"/"UTC-H".
- confidence: high = read from the official site; medium = official site but dates marked
  tentative, or from a reliable secondary source; low = uncertain.
- Finish by calling submit_result exactly once."""


def user_prompt(conf: dict) -> str:
    known = sorted(conf["editions"], key=lambda e: e["year"])[-2:]
    return (
        f"Conference: {conf['acronym']} — {conf['name']}\n"
        f"Category: {conf['category']}\n"
        f"Known homepage: {conf.get('homepage') or 'unknown'}\n"
        f"Most recent known editions (may be outdated):\n{json.dumps(known, indent=2) if known else 'none'}\n"
    )


def run_agent(conf: dict) -> dict:
    client, model = make_client()
    validator = jsonschema.Draft202012Validator(edition_schema())
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(today=today().isoformat())},
        {"role": "user", "content": user_prompt(conf)},
    ]
    tools = TOOL_SPECS + [SUBMIT_SPEC]

    for step in range(MAX_STEPS):
        last_step = step == MAX_STEPS - 1
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "submit_result"}} if last_step else "auto",
            temperature=0,
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            messages.append({"role": "user", "content": "Continue using the tools, and finish with submit_result."})
            continue

        for call in msg.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                result = f"error: invalid JSON arguments: {exc}"
            else:
                if name == "submit_result":
                    outcome = check_submission(args, validator)
                    if isinstance(outcome, dict):
                        return outcome
                    result = outcome
                elif name in TOOLS:
                    print(f"  [{conf['id']}] {name}({args})", file=sys.stderr)
                    try:
                        result = TOOLS[name](**args)
                    except TypeError as exc:
                        result = f"error: bad arguments: {exc}"
                else:
                    result = f"error: unknown tool {name}"
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    return {"status": "error", "error": f"no valid submission within {MAX_STEPS} steps"}


def check_submission(args: dict, validator: jsonschema.Validator) -> dict | str:
    """Return the final outcome, or an error string to send back to the model."""
    if not args.get("found"):
        return {"status": "not_found"}
    edition = args.get("edition")
    if not isinstance(edition, dict):
        return "error: found=true requires an edition object"
    # Drop keys outside the schema rather than rejecting the whole answer.
    allowed = set(validator.schema["$defs"]["edition"]["properties"])
    edition = {k: v for k, v in edition.items() if k in allowed}
    round_keys = set(validator.schema["$defs"]["round"]["properties"])
    edition["rounds"] = [{k: v for k, v in r.items() if k in round_keys} for r in edition.get("rounds", [])]
    # An empty list means "not found"; null keeps a previously known value in the merge.
    if edition.get("pc_chairs"):
        person_keys = set(validator.schema["$defs"]["person"]["properties"])
        edition["pc_chairs"] = [{k: v for k, v in p.items() if k in person_keys}
                                for p in edition["pc_chairs"] if isinstance(p, dict)]
    else:
        edition.pop("pc_chairs", None)
    errors = sorted(validator.iter_errors(edition), key=lambda e: list(e.path))
    if errors:
        details = "; ".join(f"{'/'.join(map(str, e.path)) or '(root)'}: {e.message}" for e in errors[:5])
        return f"error: submission does not match the schema, fix and resubmit: {details}"
    return {"status": "ok", "edition": edition}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("id", help="conference id from data/conferences.json")
    args = parser.parse_args()

    conf = next((c for c in load_data()["conferences"] if c["id"] == args.id), None)
    if conf is None:
        raise SystemExit(f"unknown conference id: {args.id}")

    try:
        outcome = run_agent(conf)
    except Exception as exc:  # noqa: BLE001 - always produce an output file
        traceback.print_exc()
        outcome = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    OUT_DIR.mkdir(exist_ok=True)
    out = {"id": conf["id"], "checked": today().isoformat(), **outcome}
    path = OUT_DIR / f"{conf['id']}.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{conf['id']}: {out['status']}" + (f" ({out['error']})" if out.get("error") else ""))


if __name__ == "__main__":
    main()
