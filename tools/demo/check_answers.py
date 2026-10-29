#!/usr/bin/env python3
"""Check that the index finds exactly what each hand-written answer key lists.

Usage:
  python3 tools/demo/check_answers.py --index <dir> [--root <repo root>] demo/stories/*.answer.json

Components have `source` "index" (the default) or "judgement".
For each key, over the components with source "index":
  (a) every non-`new` component exists in the index (and has the stated type);
  (b) the seeds plus consumers(seed, hops) for every seed equal the key's non-`new` set;
  (c) every listed hop equals the minimum hop at which the index finds the component (seed = 0).
`new` components must have hop null and must NOT exist yet.
Judgement components are things a person must weigh that the index cannot reach: hop null, an
`evidence` path (optionally path:line) that exists under --root, and they must NOT be reachable
from the seeds at the key's hops (if they are, they belong with source "index").
`assumptions` (list of strings) and `decisions` (list of {text, ownerRole}) are shape-checked.

Exit 0 when every key passes, 1 when a key fails the check, 2 on a malformed key or missing index.
"""
import argparse
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
_spec = importlib.util.spec_from_file_location(
    "query", os.path.join(os.path.dirname(HERE), "index", "query.py"))
query = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(query)

CHANGE_TYPES = {"new", "modify", "review"}
SOURCES = {"index", "judgement"}


class KeyError2(Exception):
    """A malformed key (exit 2)."""


def validate_schema(key):
    def bad(msg):
        raise KeyError2(msg)

    if not isinstance(key, dict):
        bad("key is not a JSON object")
    if key.get("version") != 1:
        bad("version must be 1")
    for f in ("storyId", "squad"):
        if not isinstance(key.get(f), str) or not key[f].strip():
            bad(f"{f} must be a non-empty string")
    seeds = key.get("seeds")
    if not isinstance(seeds, list) or not seeds or not all(isinstance(s, str) and s for s in seeds):
        bad("seeds must be a non-empty list of API names")
    hops = key.get("hops")
    if not isinstance(hops, int) or isinstance(hops, bool) or not 1 <= hops <= 3:
        bad("hops must be an integer from 1 to 3")
    comps = key.get("components")
    if not isinstance(comps, list) or not comps:
        bad("components must be a non-empty list")
    seen = set()
    for c in comps:
        if not isinstance(c, dict):
            bad("a component is not an object")
        api = c.get("api")
        if not isinstance(api, str) or not api:
            bad("a component has no api")
        if api in seen:
            bad(f"duplicate component: {api}")
        seen.add(api)
        if not isinstance(c.get("type"), str) or not c["type"]:
            bad(f"{api}: type must be a non-empty string")
        if c.get("changeType") not in CHANGE_TYPES:
            bad(f"{api}: changeType must be one of new, modify, review")
        if c.get("source", "index") not in SOURCES:
            bad(f"{api}: source must be index or judgement")
        if not isinstance(c.get("why"), str) or not c["why"].strip():
            bad(f"{api}: why must be a non-empty string")
        if "hop" not in c or not (c["hop"] is None or (isinstance(c["hop"], int) and not isinstance(c["hop"], bool) and c["hop"] >= 0)):
            bad(f"{api}: hop must be an integer or null")
        if c.get("source", "index") == "judgement" and not (isinstance(c.get("evidence"), str) and c["evidence"]):
            bad(f"{api}: a judgement component needs an evidence path")
        ev = c.get("evidence")
        if ev is not None:
            if not isinstance(ev, str) or not ev:
                bad(f"{api}: evidence must be a path string")
            if os.path.isabs(ev) or ev.startswith(("/", "\\")) or ".." in ev.replace("\\", "/").split("/"):
                bad(f"{api}: evidence must be a path inside the repo (no absolute path, no ..)")
    ass = key.get("assumptions", [])
    if not isinstance(ass, list) or not all(isinstance(a, str) and a.strip() for a in ass):
        bad("assumptions must be a list of non-empty strings")
    dec = key.get("decisions", [])
    if not isinstance(dec, list) or not all(
            isinstance(d, dict) and isinstance(d.get("text"), str) and d["text"].strip()
            and isinstance(d.get("ownerRole"), str) and d["ownerRole"].strip() for d in dec):
        bad("decisions must be a list of {text, ownerRole} with non-empty strings")


def found_hops(idx, seeds, hops):
    """api -> minimum hop over all seeds; a seed itself is hop 0."""
    found = {s: 0 for s in seeds}
    for s in seeds:
        for hit in query.consumers(idx, s, hops):
            if hit["api"] not in found or hit["hop"] < found[hit["api"]]:
                found[hit["api"]] = hit["hop"]
    return found


def check_key(idx, key, root):
    problems = []
    nodes = idx["nodes"]
    seeds = key["seeds"]
    comps = key["components"]
    for s in seeds:
        if s not in nodes:
            problems.append(f"seed not in index: {s}")
    found = found_hops(idx, [s for s in seeds if s in nodes], key["hops"])

    judgement = [c for c in comps if c.get("source", "index") == "judgement"]
    indexed = [c for c in comps if c.get("source", "index") == "index"]
    existing = [c for c in indexed if c["changeType"] != "new"]

    for c in indexed:
        if c["changeType"] == "new":
            if c.get("hop") is not None:
                problems.append(f"new component must have hop null: {c['api']}")
            if c["api"] in nodes:
                problems.append(f"new component already exists in the index: {c['api']}")
            continue
        if c["api"] not in nodes:
            problems.append(f"missing from index: {c['api']}")
        elif nodes[c["api"]].get("type") != c["type"]:
            problems.append(f"wrong type: {c['api']} key says {c['type']}, index says {nodes[c['api']].get('type')}")

    listed = {c["api"] for c in existing}
    judged = {c["api"] for c in judgement}
    for api in sorted(set(found) - listed - judged):
        problems.append(f"extra in index, not in key: {api} (hop {found[api]})")
    for api in sorted(listed - set(found)):
        problems.append(f"in key, not found by the index within {key['hops']} hops: {api}")
    for c in existing:
        if c["api"] in found and c.get("hop") != found[c["api"]]:
            problems.append(f"wrong hop: {c['api']} key says {c.get('hop')}, index minimum is {found[c['api']]}")

    for c in judgement:
        if c.get("hop") is not None:
            problems.append(f"judgement component must have hop null: {c['api']}")
        if c["api"] in nodes and nodes[c["api"]].get("type") != c["type"]:
            problems.append(f"wrong type: {c['api']} key says {c['type']}, index says {nodes[c['api']].get('type')}")
        if c["api"] in found:
            problems.append(f"judgement component is reachable from the seeds (use source index): "
                            f"{c['api']} (hop {found[c['api']]})")
        path = c["evidence"].rsplit(":", 1)[0] if c["evidence"].rsplit(":", 1)[-1].isdigit() else c["evidence"]
        if not os.path.isfile(os.path.join(root, path)):
            problems.append(f"judgement evidence file not found: {c['api']} -> {path}")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", required=True, help="directory holding metadata.json")
    ap.add_argument("--root", default=REPO, help="repo root that judgement evidence paths are relative to")
    ap.add_argument("keys", nargs="+")
    a = ap.parse_args(argv)
    try:
        idx = query.load(a.index)
    except (OSError, ValueError) as exc:
        print(f"error: cannot load index from {a.index}: {exc}", file=sys.stderr)
        return 2
    failed = False
    for path in a.keys:
        try:
            with open(path) as fh:
                key = json.load(fh)
            validate_schema(key)
        except (OSError, ValueError, KeyError2) as exc:
            print(f"error: malformed key {path}: {exc}", file=sys.stderr)
            return 2
        problems = check_key(idx, key, a.root)
        print(f"[{'FAIL' if problems else 'PASS'}] {key['storyId']} ({os.path.basename(path)})")
        for p in problems:
            print(f"    {p}")
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
