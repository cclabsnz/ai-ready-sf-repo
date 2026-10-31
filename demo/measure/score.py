#!/usr/bin/env python3
"""Score an impact record against a hand-written answer key.

Usage:
  python3 demo/measure/score.py <impact.json> --key <answer.json>

Compares the component apis in the record (`components[].api`) with the key's component apis.
Salesforce API names are case-insensitive, so the comparison ignores letter case: `found` and
`extra` keep the record's spelling, `missed` the key's. Prints JSON: {found, missed, extra, recall, precision}. Recall is found / key size and precision is
found / record size, both computed here; an empty denominator gives null. Exit 0 on a scored run,
2 on a missing or malformed input. Story scoring (story.json) is not in scope.
"""
import argparse
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
_spec = importlib.util.spec_from_file_location(
    "check_answers", os.path.join(REPO, "tools", "demo", "check_answers.py"))
check_answers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_answers)


def apis(record, label):
    comps = record.get("components") if isinstance(record, dict) else None
    if not isinstance(comps, list):
        raise ValueError(f"{label}: no components list")
    out, seen = [], set()
    for c in comps:
        if not isinstance(c, dict) or not isinstance(c.get("api"), str) or not c["api"]:
            raise ValueError(f"{label}: a component has no api")
        if c["api"].casefold() not in seen:
            seen.add(c["api"].casefold())
            out.append(c["api"])
    return out


def score(record, key):
    got, want = apis(record, "record"), apis(key, "key")
    spelling = {a.casefold(): a for a in got}
    wanted = {a.casefold() for a in want}
    found = [spelling[a.casefold()] for a in want if a.casefold() in spelling]
    missed = [a for a in want if a.casefold() not in spelling]
    extra = [a for a in got if a.casefold() not in wanted]
    return {
        "found": found, "missed": missed, "extra": extra,
        "recall": len(found) / len(want) if want else None,
        "precision": len(found) / len(got) if got else None,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("record", help="impact.json")
    ap.add_argument("--key", required=True, help="answer key (*.answer.json)")
    a = ap.parse_args(argv)
    try:
        with open(a.key, encoding="utf-8") as fh:
            key = json.load(fh)
        check_answers.validate_schema(key)
        with open(a.record, encoding="utf-8") as fh:
            record = json.load(fh)
        result = score(record, key)
    except (OSError, ValueError, check_answers.KeyError2) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
