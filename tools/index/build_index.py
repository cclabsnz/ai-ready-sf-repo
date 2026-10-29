#!/usr/bin/env python3
"""Build a SHA-stamped metadata index from a Salesforce DX checkout.

stdlib only. Walks force-app/ (and pkg-*/) and emits:
  index/metadata.json   nodes + edges
  index/inventory.json  counts and distributions

Nothing here reads an org. The index is a projection of the checkout.

Usage:
  python3 tools/index/build_index.py --root . --out index
"""
import argparse
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

INDEX_VERSION = "0.2.0"
NS = {"m": "http://soap.sforce.com/2006/04/metadata"}


def git_sha(root):
    try:
        return subprocess.check_output(
            ["git", "-C", root, "rev-parse", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def repo_root(root):
    """Top of the git checkout holding root, so every path and `path:line` opens from the repo root
    even when indexing a subfolder such as fixtures/. Falls back to root outside a checkout."""
    try:
        top = subprocess.check_output(
            ["git", "-C", root, "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL
        ).decode().strip()
        return os.path.realpath(top)
    except Exception:
        return root


def rel(base, path):
    return os.path.relpath(path, base).replace(os.sep, "/")


def text(el, tag):
    found = el.find(f"m:{tag}", NS)
    return found.text.strip() if found is not None and found.text else None


def walk(root):
    for base in sorted(os.listdir(root)):
        if base == "force-app" or base.startswith("pkg-"):
            for dirpath, _, files in os.walk(os.path.join(root, base)):
                for f in files:
                    yield os.path.join(dirpath, f)


def namespace_of(api_name, namespaces):
    for ns in namespaces:
        if api_name.startswith(ns + "__"):
            return ns
    return None


def build(root, namespaces):
    nodes, edges = {}, []
    apex_sources = {}
    base = repo_root(root)

    for path in walk(root):
        r = rel(base, path)
        name = os.path.basename(path)

        # Objects
        if name.endswith(".object-meta.xml"):
            api = name[: -len(".object-meta.xml")]
            nodes[api] = {"type": "CustomObject", "path": r,
                          "namespace": namespace_of(api, namespaces)}

        # Fields
        elif name.endswith(".field-meta.xml"):
            obj = os.path.basename(os.path.dirname(os.path.dirname(path)))
            field = name[: -len(".field-meta.xml")]
            api = f"{obj}.{field}"
            try:
                el = ET.parse(path).getroot()
                ftype = text(el, "type")
                required = text(el, "required") == "true"
            except ET.ParseError:
                ftype, required = None, None
            nodes[api] = {"type": "CustomField", "fieldType": ftype,
                          "required": required, "path": r,
                          "namespace": namespace_of(field, namespaces)}
            nodes.setdefault(obj, {"type": "CustomObject", "path": None,
                                   "namespace": namespace_of(obj, namespaces)})
            edges.append({"from": api, "to": obj, "kind": "fieldOf"})

        # Apex classes and triggers
        elif name.endswith(".cls") or name.endswith(".trigger"):
            api = name.rsplit(".", 1)[0]
            kind = "ApexClass" if name.endswith(".cls") else "ApexTrigger"
            meta = path + "-meta.xml"
            api_version = None
            if os.path.exists(meta):
                try:
                    api_version = text(ET.parse(meta).getroot(), "apiVersion")
                except ET.ParseError:
                    pass
            with open(path, encoding="utf-8", errors="replace") as fh:
                src = fh.read()
            apex_sources[api] = (r, src)
            sharing = "without sharing" if re.search(r"\bwithout\s+sharing\b", src) else (
                "with sharing" if re.search(r"\bwith\s+sharing\b", src) else "inherited/unspecified")
            nodes[api] = {"type": kind, "path": r, "apiVersion": api_version,
                          "sharing": sharing, "isTest": "@isTest" in src or "@IsTest" in src}

        # Flows
        elif name.endswith(".flow-meta.xml"):
            api = name[: -len(".flow-meta.xml")]
            try:
                el = ET.parse(path).getroot()
                ptype = text(el, "processType")
                status = text(el, "status")
            except ET.ParseError:
                ptype, status = None, None
            nodes[api] = {"type": "Flow", "processType": ptype, "status": status, "path": r}
            with open(path, encoding="utf-8", errors="replace") as fh:
                src = fh.read()
            for m in re.finditer(r"<(?:field|object)>([A-Za-z0-9_]+(?:__c|__r)?)</", src):
                edges.append({"from": api, "to": m.group(1), "kind": "flowRef",
                              "evidence": f"{r}:{src[:m.start()].count(chr(10)) + 1}"})

        # Permission sets
        elif name.endswith(".permissionset-meta.xml"):
            api = name[: -len(".permissionset-meta.xml")]
            nodes[api] = {"type": "PermissionSet", "path": r}
            try:
                el = ET.parse(path).getroot()
                for fp in el.findall("m:fieldPermissions", NS):
                    f = text(fp, "field")
                    if f:
                        edges.append({"from": api, "to": f, "kind": "fieldPermission",
                                      "editable": text(fp, "editable") == "true"})
            except ET.ParseError:
                pass

        # LWC / Aura
        elif "/lwc/" in r and name.endswith(".js") and not name.endswith(".test.js"):
            api = os.path.basename(os.path.dirname(path))
            nodes.setdefault(api, {"type": "LightningComponentBundle", "path": os.path.dirname(r)})
            with open(path, encoding="utf-8", errors="replace") as fh:
                src = fh.read()
            for m in re.finditer(r"@salesforce/apex/([A-Za-z0-9_]+)\.", src):
                edges.append({"from": api, "to": m.group(1), "kind": "lwcApexImport",
                              "evidence": f"{r}:{src[:m.start()].count(chr(10)) + 1}"})
        elif "/aura/" in r and name.endswith(".cmp"):
            api = name[:-4]
            nodes[api] = {"type": "AuraDefinitionBundle", "path": os.path.dirname(r)}

    # Apex -> field/object references (narrow, deliberate regexes)
    field_names = {k for k, v in nodes.items() if v["type"] == "CustomField"}
    short_fields = {}
    for full in field_names:
        short_fields.setdefault(full.split(".", 1)[1], []).append(full)
    for api, (r, src) in apex_sources.items():
        for i, line in enumerate(src.splitlines(), 1):
            for m in re.finditer(r"\b([A-Za-z0-9_]+__c)\b", line):
                tok = m.group(1)
                for full in short_fields.get(tok, []):
                    edges.append({"from": api, "to": full, "kind": "apexFieldRef",
                                  "evidence": f"{r}:{i}"})
                if tok in nodes and nodes[tok]["type"] == "CustomObject":
                    edges.append({"from": api, "to": tok, "kind": "apexObjectRef",
                                  "evidence": f"{r}:{i}"})

    # Resolve flow short names (<field>Risk_Rating__c</field>) to full API names when unambiguous
    for e in edges:
        if e["kind"] == "flowRef" and e["to"] not in nodes:
            full = short_fields.get(e["to"], [])
            if len(full) == 1:
                e["to"] = full[0]

    # Dedupe edges
    seen, uniq = set(), []
    for e in edges:
        key = json.dumps(e, sort_keys=True)
        if key not in seen:
            seen.add(key)
            uniq.append(e)
    return nodes, uniq


def inventory(nodes):
    by_type = {}
    for v in nodes.values():
        by_type[v["type"]] = by_type.get(v["type"], 0) + 1
    api_versions = {}
    sharing = {}
    ptypes = {}
    for v in nodes.values():
        if v["type"] in ("ApexClass", "ApexTrigger"):
            api_versions[v.get("apiVersion") or "unknown"] = api_versions.get(v.get("apiVersion") or "unknown", 0) + 1
            sharing[v["sharing"]] = sharing.get(v["sharing"], 0) + 1
        if v["type"] == "Flow":
            ptypes[v.get("processType") or "unknown"] = ptypes.get(v.get("processType") or "unknown", 0) + 1
    return {
        "byType": by_type,
        "apexByApiVersion": dict(sorted(api_versions.items())),
        "apexBySharing": sharing,
        "flowsByProcessType": ptypes,
        "auraVsLwc": {"aura": by_type.get("AuraDefinitionBundle", 0),
                      "lwc": by_type.get("LightningComponentBundle", 0)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="index")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args()
    if args.version:
        print(INDEX_VERSION)
        return 0
    root = os.path.realpath(args.root)  # realpath, to match git's top level (e.g. macOS /var -> /private/var)
    ns_file = os.path.join(root, "namespaces.json")
    namespaces = []
    if os.path.exists(ns_file):
        with open(ns_file) as fh:
            namespaces = json.load(fh).get("namespaces", [])
    nodes, edges = build(root, namespaces)
    stamp = {"commit": git_sha(root), "indexVersion": INDEX_VERSION,
             "builtAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "namespaces": namespaces}
    os.makedirs(os.path.join(root, args.out), exist_ok=True)
    with open(os.path.join(root, args.out, "metadata.json"), "w") as fh:
        json.dump({"stamp": stamp, "nodes": nodes, "edges": edges}, fh, indent=1, sort_keys=True)
    with open(os.path.join(root, args.out, "inventory.json"), "w") as fh:
        json.dump({"stamp": stamp, "inventory": inventory(nodes)}, fh, indent=1, sort_keys=True)
    print(f"indexed {len(nodes)} nodes, {len(edges)} edges at {stamp['commit'][:8]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
