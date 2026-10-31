#!/usr/bin/env python3
"""Query helpers over index/metadata.json. Skills call these, never grep.

Usage:
  python3 tools/index/query.py exists Account.Risk_Rating__c
  python3 tools/index/query.py type Account.Risk_Rating__c
  python3 tools/index/query.py consumers Account.Risk_Rating__c --hops 2
  python3 tools/index/query.py below-api-floor 58
  python3 tools/index/query.py edge-seeds Account.Service_Level__c Case
  python3 tools/index/query.py stamp
  python3 tools/index/query.py check-stale        # exit 3 if index commit != HEAD

Every answer is JSON on stdout. Zero hits is a valid answer and is reported as such.
"""
import argparse
import json
import os
import re
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


INTEGRATION_PERMSET = re.compile(r"integration", re.I)
BULK_DETAIL = "a bulk change of 200 records or more"
ORG_ONLY_DETAIL = "sharing settings and real data volumes are org configuration, not in this repo"


def first_line(root, path, needle):
    """1-based line of the first `needle` in `root/path`, or 1 when the file or needle is absent."""
    try:
        with open(os.path.join(root, path), encoding="utf-8", errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                if needle in line:
                    return n
    except OSError:
        pass
    return 1


def edge_seeds(idx, apis, root):
    """Deterministic edge-case seeds for fields and objects, from index edges and node attributes only.

    A field seed covers the field and its object; an object seed covers the object only.
    Returns {"seeds": [...], "unresolved": [api, ...]}.
    """
    nodes, edges = idx["nodes"], idx["edges"]
    object_targets = {e["to"] for e in edges if e["kind"] in ("fieldOf", "triggerOn")}
    seeds, seen = [], set()
    unresolved = []

    def add(category, component, detail, evidence, confidence="Confirmed"):
        if evidence is None and confidence == "Confirmed":
            confidence = "Unverifiable"
        key = (component, category, detail)
        if key in seen:
            return
        seen.add(key)
        seeds.append({"category": category, "component": component, "detail": detail,
                      "evidence": evidence, "confidence": confidence})

    def at(path, needle):
        return f"{path}:{first_line(root, path, needle)}" if path else None

    def field_seeds(api, node):
        path = node.get("path")
        derived = (node.get("fieldType") in ("MasterDetail", "AutoNumber", "Summary")
                   or node.get("formula"))
        if node.get("required") is False and not derived:
            ev = None
            if path:
                ev = at(path, "<required>" if _has_line(root, path, "<required>") else "<type>")
            add("blank", api, "field is not required; value left blank", ev)
        if node.get("globalValueSet"):
            add("picklist-value", api, "global value set; values not in this repo",
                at(path, "<valueSetName>"), "Unverifiable")
        for pv in node.get("picklistValues") or []:
            detail = pv["value"] + ("" if pv.get("active", True) else " (inactive)")
            add("picklist-value", api, detail, f"{path}:{pv['line']}" if path else None)
        for e in edges:
            if e["kind"] == "fieldPermission" and e["to"] == api:
                add("field-access", api, f"{e['from']} {'edit' if e.get('editable') else 'read'}",
                    e.get("evidence"))

    def object_seeds(obj):
        node = nodes.get(obj, {})
        trigger_ev = None
        for e in sorted((e for e in edges if e["to"] == obj), key=lambda e: (e["kind"], e["from"])):
            src = nodes.get(e["from"], {})
            if e["kind"] == "recordTypeOf":
                add("record-type", obj, f"record type {e['from']}", e.get("evidence"))
            elif e["kind"] == "validationRuleOf":
                state = {True: "active", False: "inactive"}.get(src.get("active"), "status unknown")
                add("automation", obj, f"validation rule {e['from']} ({state})", e.get("evidence"))
            elif e["kind"] == "flowTriggerObject":
                add("automation", obj, f"flow {e['from']} ({src.get('status') or 'status unknown'})",
                    e.get("evidence"))
            elif e["kind"] == "triggerOn":
                add("automation", obj, f"trigger {e['from']} (status not in index)", e.get("evidence"))
                if trigger_ev is None:
                    trigger_ev = e.get("evidence")
        add("bulk", obj, BULK_DETAIL, trigger_ev or at(node.get("path"), "<CustomObject"))
        # Sharing settings and real data volumes live in the org, never in this repo.
        add("org-only", obj, ORG_ONLY_DETAIL, None, "Unverifiable")
        prefix = obj + "."
        for e in sorted(edges, key=lambda e: (e["from"], e["to"])):
            if (e["kind"] == "fieldPermission" and e["to"].startswith(prefix)
                    and INTEGRATION_PERMSET.search(e["from"])):
                add("integration-user", obj, f"{e['from']} may write as an integration user",
                    e.get("evidence"), "Inferred")

    objects = []
    for api in apis:
        node = nodes.get(api)
        if node is None:
            if api not in unresolved:
                unresolved.append(api)
        elif node.get("type") == "CustomField" and "." in api:
            field_seeds(api, node)
            objects.append(api.split(".", 1)[0])
        elif node.get("type") == "CustomObject" or ("." not in api and api in object_targets):
            objects.append(api)
        elif api not in unresolved:
            unresolved.append(api)
    for obj in dict.fromkeys(objects):
        object_seeds(obj)
    seeds.sort(key=lambda s: (s["component"], s["category"], s["detail"]))
    return {"seeds": seeds, "unresolved": unresolved}


def _has_line(root, path, needle):
    try:
        with open(os.path.join(root, path), encoding="utf-8", errors="replace") as fh:
            return needle in fh.read()
    except OSError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["exists", "type", "consumers", "below-api-floor", "stamp", "check-stale",
                                    "edge-seeds"])
    ap.add_argument("arg", nargs="*")
    ap.add_argument("--hops", type=int, default=2)
    ap.add_argument("--index", default="index")
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    if a.cmd != "edge-seeds":
        if len(a.arg) > 1:
            ap.error("unrecognized arguments: " + " ".join(a.arg[1:]))
        a.arg = a.arg[0] if a.arg else None
    elif not a.arg:
        ap.error("edge-seeds needs at least one api name")
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
    elif a.cmd == "edge-seeds":
        print(json.dumps(edge_seeds(idx, a.arg, a.root)))
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
