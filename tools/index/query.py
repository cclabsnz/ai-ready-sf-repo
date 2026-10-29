#!/usr/bin/env python3
"""Query helpers over index/metadata.json. Skills call these, never grep.

Usage:
  python3 tools/index/query.py exists Account.Risk_Rating__c
  python3 tools/index/query.py type Account.Risk_Rating__c
  python3 tools/index/query.py consumers Account.Risk_Rating__c --hops 2
  python3 tools/index/query.py below-api-floor 58
  python3 tools/index/query.py stamp
  python3 tools/index/query.py check-stale        # exit 3 if index commit != HEAD

Every answer is JSON on stdout. Zero hits is a valid answer and is reported as such.
"""
import argparse
import json
import os
import subprocess
import sys


def load(index_dir):
    with open(os.path.join(index_dir, "metadata.json")) as fh:
        return json.load(fh)


def head_sha(root):
    try:
        return subprocess.check_output(["git", "-C", root, "rev-parse", "HEAD"],
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "unknown"


def consumers(idx, api, hops):
    """Everything that references `api`, expanded up to `hops` levels. Bounded by design."""
    out, frontier, seen = [], {api}, {api}
    for hop in range(1, hops + 1):
        nxt = set()
        for e in idx["edges"]:
            if e["to"] in frontier and e["from"] not in seen:
                node = idx["nodes"].get(e["from"], {})
                out.append({"api": e["from"], "type": node.get("type"), "via": e["kind"],
                            "target": e["to"], "hop": hop, "evidence": e.get("evidence")})
                nxt.add(e["from"])
                seen.add(e["from"])
        frontier = nxt
        if not frontier:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["exists", "type", "consumers", "below-api-floor", "stamp", "check-stale"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--hops", type=int, default=2)
    ap.add_argument("--index", default="index")
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    idx = load(a.index)
    nodes = idx["nodes"]

    if a.cmd == "stamp":
        print(json.dumps(idx["stamp"]))
    elif a.cmd == "check-stale":
        head = head_sha(a.root)
        stale = head != idx["stamp"]["commit"]
        print(json.dumps({"indexCommit": idx["stamp"]["commit"], "head": head, "stale": stale}))
        return 3 if stale else 0
    elif a.cmd == "exists":
        print(json.dumps({"api": a.arg, "exists": a.arg in nodes,
                          "note": None if a.arg in nodes else "zero hits in index; pattern searched: exact API name"}))
    elif a.cmd == "type":
        n = nodes.get(a.arg)
        print(json.dumps({"api": a.arg, "node": n, "found": n is not None}))
    elif a.cmd == "consumers":
        hops = max(1, min(a.hops, 3))
        hits = consumers(idx, a.arg, hops)
        print(json.dumps({"api": a.arg, "hops": hops, "count": len(hits), "consumers": hits,
                          "note": None if hits else "zero consumers in index; edges searched: all kinds"}))
    elif a.cmd == "below-api-floor":
        floor = float(a.arg)
        hits = [{"api": k, "apiVersion": v.get("apiVersion"), "path": v["path"]}
                for k, v in nodes.items()
                if v["type"] in ("ApexClass", "ApexTrigger") and v.get("apiVersion")
                and float(v["apiVersion"]) < floor]
        print(json.dumps({"floor": floor, "count": len(hits), "items": sorted(hits, key=lambda x: x["apiVersion"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
