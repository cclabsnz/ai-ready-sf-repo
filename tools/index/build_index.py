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

INDEX_VERSION = "0.4.0"
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


def line_of(src, needle, start=0):
    """1-based line of the first `needle` at or after offset `start`, or 1 if absent."""
    i = src.find(needle, start)
    return 1 if i < 0 else src.count("\n", 0, i) + 1


def find_line(src, needle, pos):
    """(1-based line, next offset) of `needle` at or after `pos`; (1, pos) when absent."""
    i = src.find(needle, pos)
    if i < 0:
        return 1, pos
    return src.count("\n", 0, i) + 1, i + 1


def parse_xml(path):
    """Root element of an XML file, or None when it cannot be parsed. Malformed input marks the
    node (parseError) instead of stopping the build."""
    try:
        return ET.parse(path).getroot()
    except (ET.ParseError, OSError, ValueError, UnicodeError):
        return None


_LITERALS = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|/\*.*?\*/", re.S)
# Apex: '...' strings, /* */ and // comments. Alternatives are tried left to right at each offset,
# so a quote inside a comment, or // inside a string, is consumed by whichever starts first.
_APEX_LITERALS = re.compile(r"'(?:\\.|[^'\\])*'|/\*.*?\*/|//[^\n]*", re.S)


def _blank(pattern, s):
    return pattern.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), s)


def blank_literals(formula):
    """Blank '...' and "..." literals (with \\ escapes) and /* ... */ comments, keeping newlines so
    offsets and line numbers are unchanged."""
    return _blank(_LITERALS, formula)


def blank_apex(src):
    """Blank '...' strings, /* ... */ and // comments in Apex, keeping newlines and offsets."""
    return _blank(_APEX_LITERALS, src)


def read_src(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


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
    vr_formulas = []    # (rule, object, path, formula, formula start line)
    rt_picklists = []   # (record type, object, picklist, path, line)
    flexi_fields = []   # (page, object, field, path, line)
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
            el = parse_xml(path)
            ftype = text(el, "type") if el is not None else None
            required = (text(el, "required") == "true") if el is not None else None
            nodes[api] = {"type": "CustomField", "fieldType": ftype,
                          "required": required, "path": r,
                          "namespace": namespace_of(field, namespaces)}
            if el is None:
                nodes[api]["parseError"] = True
            nodes.setdefault(obj, {"type": "CustomObject", "path": None,
                                   "namespace": namespace_of(obj, namespaces)})
            edges.append({"from": api, "to": obj, "kind": "fieldOf"})

        # Apex classes and triggers
        elif name.endswith(".cls") or name.endswith(".trigger"):
            api = name.rsplit(".", 1)[0]
            kind = "ApexClass" if name.endswith(".cls") else "ApexTrigger"
            meta = path + "-meta.xml"
            api_version, meta_bad = None, False
            if os.path.exists(meta):
                mel = parse_xml(meta)
                if mel is None:
                    meta_bad = True
                else:
                    api_version = text(mel, "apiVersion")
            src = read_src(path)
            apex_sources[api] = (r, src)
            code = blank_apex(src)  # sharing is read from code only, never from comments or strings
            sharing = "without sharing" if re.search(r"\bwithout\s+sharing\b", code) else (
                "with sharing" if re.search(r"\bwith\s+sharing\b", code) else "inherited/unspecified")
            nodes[api] = {"type": kind, "path": r, "apiVersion": api_version,
                          "sharing": sharing,
                          # from code only (Apex annotations are case-insensitive), never comments or strings
                          "isTest": re.search(r"@isTest\b", code, re.I) is not None}
            if meta_bad:
                nodes[api]["parseError"] = True
            if kind == "ApexClass":
                nodes[api]["invocable"] = re.search(r"@InvocableMethod\b", code, re.I) is not None
                nodes[api]["auraEnabledMethods"] = sorted(set(re.findall(
                    r"@AuraEnabled\b(?:\s*\([^)]*\))?(?:\s*@\w+(?:\s*\([^)]*\))?)*"
                    r"\s+(?:public|global)\s+static\s+[\w.<>,\[\]\s]+?\s+(\w+)\s*\(",
                    code, re.I)))
            else:
                tm = re.search(r"\btrigger\s+\w+\s+on\s+(\w+)\s*\(", code, re.I)
                if tm:
                    obj = tm.group(1)
                    nodes.setdefault(obj, {"type": "CustomObject", "path": None,
                                           "namespace": namespace_of(obj, namespaces)})
                    edges.append({"from": api, "to": obj, "kind": "triggerOn",
                                  "evidence": f"{r}:{line_of(code, tm.group(0))}"})

        # Flows
        elif name.endswith(".flow-meta.xml"):
            api = name[: -len(".flow-meta.xml")]
            el = parse_xml(path)
            ptype = text(el, "processType") if el is not None else None
            status = text(el, "status") if el is not None else None
            nodes[api] = {"type": "Flow", "processType": ptype, "status": status, "path": r}
            if el is None:
                nodes[api]["parseError"] = True
            src = read_src(path)
            for m in re.finditer(r"<(?:field|object)>([A-Za-z0-9_]+(?:__c|__r)?)</", src):
                edges.append({"from": api, "to": m.group(1), "kind": "flowRef",
                              "evidence": f"{r}:{src[:m.start()].count(chr(10)) + 1}"})
            if el is not None:
                pos = 0
                for ac in el.findall("m:actionCalls", NS):
                    _, pos = find_line(src, "<actionCalls>", pos)
                    aname = text(ac, "actionName")
                    if aname and text(ac, "actionType") == "apex":
                        ln, _ = find_line(src, f"<actionName>{aname}</actionName>", pos)
                        edges.append({"from": api, "to": aname, "kind": "flowApexAction",
                                      "evidence": f"{r}:{ln}"})
                start = el.find("m:start", NS)
                sobj = text(start, "object") if start is not None else None
                if sobj:
                    nodes.setdefault(sobj, {"type": "CustomObject", "path": None,
                                            "namespace": namespace_of(sobj, namespaces)})
                    ln, _ = find_line(src, f"<object>{sobj}</object>", max(src.find("<start>"), 0))
                    edges.append({"from": api, "to": sobj, "kind": "flowTriggerObject",
                                  "evidence": f"{r}:{ln}"})

        # Permission sets
        elif name.endswith(".permissionset-meta.xml"):
            api = name[: -len(".permissionset-meta.xml")]
            nodes[api] = {"type": "PermissionSet", "path": r}
            el = parse_xml(path)
            if el is None:
                nodes[api]["parseError"] = True
            else:
                src = read_src(path)
                pos = 0
                for fp in el.findall("m:fieldPermissions", NS):
                    f = text(fp, "field")
                    if f:
                        ln, pos = find_line(src, f"<field>{f}</field>", pos)
                        edges.append({"from": api, "to": f, "kind": "fieldPermission",
                                      "editable": text(fp, "editable") == "true",
                                      "evidence": f"{r}:{ln}"})
                pos = 0
                for op in el.findall("m:objectPermissions", NS):
                    o = text(op, "object")
                    if o:
                        ln, pos = find_line(src, f"<object>{o}</object>", pos)
                        edges.append({"from": api, "to": o, "kind": "objectPermission",
                                      "allowEdit": text(op, "allowEdit") == "true",
                                      "evidence": f"{r}:{ln}"})
                pos = 0
                for ca in el.findall("m:classAccesses", NS):
                    c = text(ca, "apexClass")
                    if c:
                        ln, pos = find_line(src, f"<apexClass>{c}</apexClass>", pos)
                        if text(ca, "enabled") == "true":
                            edges.append({"from": api, "to": c, "kind": "classAccess",
                                          "evidence": f"{r}:{ln}"})

        # FlexiPages
        elif name.endswith(".flexipage-meta.xml"):
            api = name[: -len(".flexipage-meta.xml")]
            nodes[api] = {"type": "FlexiPage", "path": r}
            el = parse_xml(path)
            if el is None:
                nodes[api]["parseError"] = True
                continue
            src = read_src(path)
            pos = 0
            for cn in el.iter(f"{{{NS['m']}}}componentName"):
                v = (cn.text or "").strip()
                if v.startswith("c:") and len(v) > 2:  # only the c namespace; force:, flexipage: etc. are platform
                    ln, pos = find_line(src, f"<componentName>{v}</componentName>", pos)
                    edges.append({"from": api, "to": v[2:], "kind": "flexipageComponent",
                                  "evidence": f"{r}:{ln}"})
            sobj = text(el, "sobjectType")
            if sobj:
                nodes.setdefault(sobj, {"type": "CustomObject", "path": None,
                                        "namespace": namespace_of(sobj, namespaces)})
                edges.append({"from": api, "to": sobj, "kind": "flexipageObject",
                              "evidence": f"{r}:{line_of(src, '<sobjectType>')}"})
                pos = 0
                for fi in el.iter(f"{{{NS['m']}}}fieldItem"):
                    v = (fi.text or "").strip()
                    if v.startswith("Record.") and len(v) > 7:
                        ln, pos = find_line(src, f"<fieldItem>{v}</fieldItem>", pos)
                        flexi_fields.append((api, sobj, v[7:], r, ln))

        # Validation rules
        elif name.endswith(".validationRule-meta.xml"):
            obj = os.path.basename(os.path.dirname(os.path.dirname(path)))
            api = f"{obj}.{name[: -len('.validationRule-meta.xml')]}"
            el = parse_xml(path)
            nodes[api] = {"type": "ValidationRule", "path": r,
                          "active": (text(el, "active") == "true") if el is not None else None}
            nodes.setdefault(obj, {"type": "CustomObject", "path": None,
                                   "namespace": namespace_of(obj, namespaces)})
            if el is None:
                nodes[api]["parseError"] = True
                continue
            src = read_src(path)
            edges.append({"from": api, "to": obj, "kind": "validationRuleOf",
                          "evidence": f"{r}:{line_of(src, '<ValidationRule')}"})
            fel = el.find("m:errorConditionFormula", NS)
            formula = fel.text if fel is not None else None  # raw: keeps leading newlines for line math
            if formula:
                vr_formulas.append((api, obj, r, formula,
                                    line_of(src, "<errorConditionFormula")))

        # Record types
        elif name.endswith(".recordType-meta.xml"):
            obj = os.path.basename(os.path.dirname(os.path.dirname(path)))
            api = f"{obj}.{name[: -len('.recordType-meta.xml')]}"
            el = parse_xml(path)
            nodes[api] = {"type": "RecordType", "path": r}
            nodes.setdefault(obj, {"type": "CustomObject", "path": None,
                                   "namespace": namespace_of(obj, namespaces)})
            if el is None:
                nodes[api]["parseError"] = True
                continue
            src = read_src(path)
            edges.append({"from": api, "to": obj, "kind": "recordTypeOf",
                          "evidence": f"{r}:{line_of(src, '<RecordType')}"})
            for pv in el.findall("m:picklistValues", NS):
                pick = text(pv, "picklist")
                if pick:
                    rt_picklists.append((api, obj, pick, r,
                                         line_of(src, f"<picklist>{pick}</picklist>")))

        # LWC / Aura
        elif "/lwc/" in r and name.endswith(".js") and not name.endswith(".test.js"):
            api = os.path.basename(os.path.dirname(path))
            nodes.setdefault(api, {"type": "LightningComponentBundle", "path": os.path.dirname(r)})
            src = read_src(path)
            for m in re.finditer(r"@salesforce/apex/([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)", src):
                # `to` stays the class (not a method node) so hop depth is unchanged;
                # auraEnabled is resolved in the post-pass once every class is known.
                edges.append({"from": api, "to": m.group(1), "kind": "lwcApexImport",
                              "method": m.group(2), "auraEnabled": None,
                              "evidence": f"{r}:{src[:m.start()].count(chr(10)) + 1}"})
        elif "/aura/" in r and name.endswith(".cmp"):
            api = name[:-4]
            nodes[api] = {"type": "AuraDefinitionBundle", "path": os.path.dirname(r)}

    # Apex -> field/object references (narrow, deliberate regexes)
    field_names = {k for k, v in nodes.items() if v["type"] == "CustomField"}
    short_fields = {}
    for full in field_names:
        short_fields.setdefault(full.split(".", 1)[1], []).append(full)
    # Comments and strings are blanked first (newlines kept), as for apexClassRef below, so a field
    # named only in a comment or a string literal makes no edge and line numbers are unchanged.
    for api, (r, src) in apex_sources.items():
        for i, line in enumerate(blank_apex(src).splitlines(), 1):
            for m in re.finditer(r"\b([A-Za-z0-9_]+__c)\b", line):
                tok = m.group(1)
                for full in short_fields.get(tok, []):
                    edges.append({"from": api, "to": full, "kind": "apexFieldRef",
                                  "evidence": f"{r}:{i}"})
                if tok in nodes and nodes[tok]["type"] == "CustomObject":
                    edges.append({"from": api, "to": tok, "kind": "apexObjectRef",
                                  "evidence": f"{r}:{i}"})

    # Apex class/trigger -> Apex class. Comments and strings are blanked first (newlines kept), so
    # tokens are whole identifiers outside both. One edge per (from, to) at the first matching line.
    class_names = {k for k, v in nodes.items() if v["type"] == "ApexClass"}
    for api, (r, src) in apex_sources.items():
        seen_to = set()
        for m in re.finditer(r"\b([A-Z][A-Za-z0-9_]*)\b", blank_apex(src)):
            tok = m.group(1)
            if tok == api or tok not in class_names or tok in seen_to:
                continue
            seen_to.add(tok)
            edges.append({"from": api, "to": tok, "kind": "apexClassRef",
                          "evidence": f"{r}:{src.count(chr(10), 0, m.start()) + 1}"})

    # LWC -> Apex import: is the imported method @AuraEnabled on that class?
    for e in edges:
        if e["kind"] == "lwcApexImport" and nodes.get(e["to"], {}).get("type") == "ApexClass":
            e["auraEnabled"] = e["method"] in nodes[e["to"]]["auraEnabledMethods"]  # None = class not indexed

    # Validation rule formulas -> fields. Bare X__c is a field on the rule's own object;
    # Obj.X__c is used only when Obj is an object node. Edges only to field nodes that exist.
    for api, obj, r, formula, start in vr_formulas:
        formula = blank_literals(formula)
        for m in re.finditer(r"(?<![A-Za-z0-9_.])(?:([A-Za-z0-9_]+)\.)?([A-Za-z0-9_]+__c)\b", formula):
            qual, tok = m.group(1), m.group(2)
            if qual is None:
                target = f"{obj}.{tok}"
            elif nodes.get(qual, {}).get("type") == "CustomObject":
                target = f"{qual}.{tok}"
            else:
                continue
            if nodes.get(target, {}).get("type") == "CustomField":
                edges.append({"from": api, "to": target, "kind": "validationFieldRef",
                              "evidence": f"{r}:{start + formula.count(chr(10), 0, m.start())}"})

    for api, obj, pick, r, line in rt_picklists:
        target = f"{obj}.{pick}"
        if nodes.get(target, {}).get("type") == "CustomField":
            edges.append({"from": api, "to": target, "kind": "recordTypePicklist",
                          "evidence": f"{r}:{line}"})

    for api, obj, fld, r, ln in flexi_fields:
        target = f"{obj}.{fld}"
        if nodes.get(target, {}).get("type") == "CustomField":
            edges.append({"from": api, "to": target, "kind": "flexipageField",
                          "evidence": f"{r}:{ln}"})

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
