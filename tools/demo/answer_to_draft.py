#!/usr/bin/env python3
"""Turn a reviewed answer key into a draft impact through the real writer. stdlib only.

  python3 tools/demo/answer_to_draft.py --key demo/stories/DEMO-202.answer.json \
      --slug round-robin-assignment --index index [--root .]

Writes classified.json and meta.json to <root>/ai-context/<id>-<slug>/scan/, then runs
write_report.py (from this checkout) by subprocess. Evidence comes from the index: a seed is
'<node path>:1'; any other index component takes the edge evidence for its smallest hop; a
judgement component takes its evidence path with ':1'. A component the index cannot place exits 1.

Exit codes: 0 ok, 1 component not found / writer failed validation, 2 bad usage or malformed key.
Code comes from this checkout (located from __file__); data comes from --root.
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
WRITER = os.path.join(REPO, "framework", "skills", "story-impact", "scripts", "write_report.py")
sys.path.insert(0, os.path.join(REPO, "tools", "impacts"))

from validate import STORY_RE, SLUG_RE  # noqa: E402

_spec = importlib.util.spec_from_file_location("query", os.path.join(REPO, "tools", "index", "query.py"))
query = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(query)

_spec2 = importlib.util.spec_from_file_location("check_answers", os.path.join(HERE, "check_answers.py"))
check_answers = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(check_answers)

IMPACT = {"modify": "Medium", "review": "Low"}
LAYERS = {"ApexClass": "Apex", "ApexTrigger": "Apex", "Queue": "Declarative"}


def usage(msg):
    print(msg, file=sys.stderr)
    return 2


def with_line(ev):
    tail = ev.rsplit(":", 1)[-1]
    return ev if ":" in ev and tail.isdigit() else ev + ":1"


def best_edges(idx, seeds, hops):
    """api -> (hop, evidence): smallest hop; ties go to the first evidence in sorted order."""
    best = {}
    for s in seeds:
        for hit in query.consumers(idx, s, hops):
            cand = (hit["hop"], hit.get("evidence") or "")
            if hit["api"] not in best or cand < best[hit["api"]]:
                best[hit["api"]] = cand
    return best


def build(key, idx):
    """Return (rows, missing)."""
    nodes = idx["nodes"]
    seeds = key["seeds"]
    best = best_edges(idx, [s for s in seeds if s in nodes], key["hops"])
    rows, missing = [], []
    for c in key["components"]:
        api = c["api"]
        judgement = c.get("source", "index") == "judgement"
        evidence = None
        if judgement:
            evidence = with_line(c["evidence"])
        elif api in seeds and api in nodes:
            evidence = nodes[api]["path"] + ":1"
        elif api in best and best[api][1]:
            evidence = best[api][1]
        elif c["changeType"] == "new":
            evidence = None
        else:
            missing.append(api)
            continue
        hop = c.get("hop")
        rows.append({"api": api, "layer": LAYERS.get(c["type"], "Other"), "type": c["type"],
                     "ownership": "Custom", "changeType": c["changeType"],
                     "impact": IMPACT.get(c["changeType"], "Low"), "scale": "", "hop": hop,
                     "evidence": evidence, "confidence": "Inferred" if judgement else "Confirmed"})
    return rows, missing


def write_json(path, obj):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Draft an impact record from a reviewed answer key.")
    ap.add_argument("--key", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--index", required=True)
    ap.add_argument("--root", default=".")
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        with open(a.key, encoding="utf-8") as fh:
            key = json.load(fh)
        check_answers.validate_schema(key)
        idx = query.load(a.index)
    except (OSError, ValueError, check_answers.KeyError2) as exc:
        return usage("cannot read key or index: %s" % exc)
    if not STORY_RE.match(key["storyId"]):
        return usage("storyId '%s' does not match %s" % (key["storyId"], STORY_RE.pattern))
    if not SLUG_RE.match(a.slug):
        return usage("--slug '%s' does not match %s" % (a.slug, SLUG_RE.pattern))

    rows, missing = build(key, idx)
    if missing:
        for api in missing:
            print("not found in the index within %d hops, no evidence to cite: %s" % (key["hops"], api),
                  file=sys.stderr)
        return 1

    base = os.path.realpath(a.root)
    ctx = os.path.join(base, "ai-context")
    scan = os.path.join(a.root, "ai-context", "%s-%s" % (key["storyId"], a.slug), "scan")
    if os.path.realpath(os.path.join(a.root, "ai-context")) != ctx or \
            not os.path.realpath(scan).startswith(ctx + os.sep):
        return usage("output folder resolves outside <root>/ai-context/; nothing written")
    os.makedirs(scan, exist_ok=True)
    meta = {"squad": key["squad"], "hops": key["hops"],
            "model": "none (derived from reviewed answer key)", "assistantVersion": "n/a",
            "decisions": key.get("decisions", []), "unknowns": list(key.get("assumptions", []))}
    cpath = os.path.join(scan, "classified.json")
    mpath = os.path.join(scan, "meta.json")
    write_json(cpath, rows)
    write_json(mpath, meta)

    p = subprocess.run([sys.executable, WRITER, "--id", key["storyId"], "--slug", a.slug,
                        "--classified", cpath, "--meta", mpath, "--root", a.root],
                       capture_output=True, text=True)
    sys.stdout.write(p.stdout)
    sys.stderr.write(p.stderr)
    return p.returncode


if __name__ == "__main__":
    sys.exit(main())
