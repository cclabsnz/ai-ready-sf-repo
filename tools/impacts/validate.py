#!/usr/bin/env python3
"""Validate impact.json records.

Usage:
  validate.py <file>... [--stage draft|promoted] [--check-evidence] [--root .]
  validate.py --all [--root .]

--all validates every <root>/impacts/*/impact.json as promoted, checks that each
folder is named <storyId>-<slug>, and that storyIds are unique.

Prints JSON on stdout. Exit codes: 0 valid, 1 validation failure, 2 bad usage.
Stdlib only. Data comes from --root; code never does.
"""
import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

STORY_RE = re.compile(r"^[A-Z][A-Z0-9]*-[0-9]+$")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
CHANGE_TYPES = ("new", "modify", "delete", "review")
IMPACTS = ("High", "Medium", "Low", "None")
LABELS = ("Confirmed", "Inferred", "Unverifiable")
STATUSES = ("draft", "in-flight", "shipped")

TOP_REQUIRED = ("schemaVersion", "storyId", "slug", "squad", "status", "provenance",
                "components", "decisions", "unknowns")
TOP_ALLOWED = TOP_REQUIRED + ("confirmedBy",)
PROV_STRINGS = ("frameworkVersion", "model", "assistantVersion")
COMP_KEYS = ("api", "type", "changeType", "impact", "confidence", "hop", "evidence", "path")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _nonempty(v):
    return isinstance(v, str) and v.strip() != ""


def load_squads(root):
    """Return the squad list from <root>/impacts/squads.json, or None when absent."""
    path = os.path.join(root, "impacts", "squads.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    squads = data.get("squads") if isinstance(data, dict) else None
    if not isinstance(squads, list) or not all(isinstance(s, str) for s in squads):
        raise ValueError("impacts/squads.json: 'squads' is not a list of strings")
    return squads


def split_evidence(ev):
    """Split 'path:line' on the last colon. Returns (path, line) or None when malformed."""
    if not isinstance(ev, str) or ":" not in ev:
        return None
    path, _, line = ev.rpartition(":")
    if not path or not re.fullmatch(r"[0-9]+", line) or int(line) < 1:
        return None
    return path, int(line)


def _check_evidence_file(root, path, line):
    base = os.path.realpath(root)
    full = os.path.realpath(os.path.join(base, path))
    if full != base and not full.startswith(base + os.sep):
        return "resolves outside the root"
    if not os.path.isfile(full):
        return "file does not exist"
    with open(full, "rb") as fh:
        count = len(fh.read().splitlines())
    if line > count:
        return "line %d is past the end of the file (%d lines)" % (line, count)
    return None


def _validate_component(i, c, root, check_evidence, errors):
    tag = "components[%d]" % i
    if not isinstance(c, dict):
        errors.append("%s: not an object" % tag)
        return
    for k in c:
        if k not in COMP_KEYS:
            errors.append("%s: unknown key '%s'" % (tag, k))
    for k in COMP_KEYS:
        if k not in c:
            errors.append("%s: missing key '%s'" % (tag, k))
    for k in ("api", "type"):
        if k in c and not _nonempty(c[k]):
            errors.append("%s: %s is not a non-empty string" % (tag, k))
    for k, allowed in (("changeType", CHANGE_TYPES), ("impact", IMPACTS), ("confidence", LABELS)):
        if k in c and c[k] not in allowed:
            errors.append("%s: %s '%s' is not one of %s" % (tag, k, c[k], ", ".join(allowed)))
    if "hop" in c and c["hop"] is not None and not (_is_int(c["hop"]) and c["hop"] >= 0):
        errors.append("%s: hop is not an integer >= 0 or null" % tag)
    if "path" in c and c["path"] is not None and not isinstance(c["path"], str):
        errors.append("%s: path is not a string or null" % tag)
    if "evidence" in c:
        ev = c["evidence"]
        if ev is None:
            if c.get("changeType") != "new" and c.get("confidence") != "Unverifiable":
                errors.append("%s: evidence is null; allowed only for changeType new or "
                              "confidence Unverifiable" % tag)
        else:
            parsed = split_evidence(ev)
            if parsed is None:
                errors.append("%s: evidence '%s' is not 'path:line' with an integer line >= 1"
                              % (tag, ev))
            elif check_evidence:
                problem = _check_evidence_file(root, parsed[0], parsed[1])
                if problem:
                    errors.append("%s: evidence '%s': %s" % (tag, ev, problem))


def validate(doc, stage, root, check_evidence=False):
    """Return a list of error strings; empty when the record is valid."""
    errors = []
    if stage not in ("draft", "promoted"):
        return ["stage '%s' is not draft or promoted" % stage]
    if not isinstance(doc, dict):
        return ["record is not a JSON object"]

    for k in doc:
        if k not in TOP_ALLOWED:
            errors.append("unknown top-level key '%s'" % k)
    for k in TOP_REQUIRED:
        if k not in doc:
            errors.append("missing top-level key '%s'" % k)

    if "schemaVersion" in doc and not (_is_int(doc["schemaVersion"]) and doc["schemaVersion"] == 1):
        errors.append("schemaVersion is not 1")
    if "storyId" in doc and not (isinstance(doc["storyId"], str) and STORY_RE.match(doc["storyId"])):
        errors.append("storyId '%s' does not match %s" % (doc["storyId"], STORY_RE.pattern))
    if "slug" in doc and not (isinstance(doc["slug"], str) and SLUG_RE.match(doc["slug"])):
        errors.append("slug '%s' does not match %s" % (doc["slug"], SLUG_RE.pattern))

    if "squad" in doc:
        if not _nonempty(doc["squad"]):
            errors.append("squad is not a non-empty string")
        else:
            try:
                squads = load_squads(root)
            except (ValueError, OSError) as exc:
                errors.append("squad list unreadable: %s" % exc)
                squads = None
            if squads is not None and doc["squad"] not in squads:
                errors.append("squad '%s' is not listed in impacts/squads.json" % doc["squad"])

    if "status" in doc:
        st = doc["status"]
        if st not in STATUSES:
            errors.append("status '%s' is not one of %s" % (st, ", ".join(STATUSES)))
        elif stage == "draft" and st != "draft":
            errors.append("status '%s': a draft record has status draft" % st)
        elif stage == "promoted" and st not in ("in-flight", "shipped"):
            errors.append("status '%s': a promoted record has status in-flight or shipped" % st)

    if "confirmedBy" in doc:
        if stage == "draft":
            errors.append("confirmedBy is present in a draft record")
        elif not _nonempty(doc["confirmedBy"]):
            errors.append("confirmedBy is empty")
    elif stage == "promoted":
        errors.append("confirmedBy is missing from a promoted record")

    prov = doc.get("provenance")
    if "provenance" in doc:
        if not isinstance(prov, dict):
            errors.append("provenance is not an object")
        else:
            allowed = ("indexStamp", "hops") + PROV_STRINGS
            for k in prov:
                if k not in allowed:
                    errors.append("provenance: unknown key '%s'" % k)
            stamp = prov.get("indexStamp")
            if not isinstance(stamp, dict) or not _nonempty(stamp.get("commit")):
                errors.append("provenance.indexStamp is not an object with a commit string")
            for k in PROV_STRINGS:
                if not _nonempty(prov.get(k)):
                    errors.append("provenance.%s is not a non-empty string" % k)
            hops = prov.get("hops")
            if not (_is_int(hops) and 1 <= hops <= 3):
                errors.append("provenance.hops is not an integer from 1 to 3")

    comps = doc.get("components")
    if "components" in doc:
        if not isinstance(comps, list):
            errors.append("components is not a list")
        else:
            seen = set()
            for i, c in enumerate(comps):
                _validate_component(i, c, root, check_evidence, errors)
                api = c.get("api") if isinstance(c, dict) else None
                if isinstance(api, str):
                    if api in seen:
                        errors.append("components[%d]: duplicate api '%s'" % (i, api))
                    seen.add(api)

    decs = doc.get("decisions")
    if "decisions" in doc:
        if not isinstance(decs, list):
            errors.append("decisions is not a list")
        else:
            for i, d in enumerate(decs):
                tag = "decisions[%d]" % i
                if not isinstance(d, dict):
                    errors.append("%s: not an object" % tag)
                    continue
                for k in d:
                    if k not in ("text", "ownerRole"):
                        errors.append("%s: unknown key '%s'" % (tag, k))
                for k in ("text", "ownerRole"):
                    if not _nonempty(d.get(k)):
                        errors.append("%s: %s is not a non-empty string" % (tag, k))

    unk = doc.get("unknowns")
    if "unknowns" in doc:
        if not isinstance(unk, list) or not all(isinstance(u, str) for u in unk):
            errors.append("unknowns is not a list of strings")

    return errors


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, ValueError) as exc:
        return None, "cannot read JSON: %s" % exc


def _run_files(files, stage, root, check_evidence):
    results = []
    for f in files:
        doc, err = _load_json(f)
        errs = [err] if err else validate(doc, stage, root, check_evidence)
        results.append({"file": f, "errors": errs})
    return results


def _run_all(root):
    results = []
    by_story = {}
    paths = sorted(glob.glob(os.path.join(root, "impacts", "*", "impact.json")))
    for p in paths:
        folder = os.path.basename(os.path.dirname(p))
        doc, err = _load_json(p)
        errs = [err] if err else validate(doc, "promoted", root)
        if not err and isinstance(doc, dict):
            sid, slug = doc.get("storyId"), doc.get("slug")
            if isinstance(sid, str) and isinstance(slug, str) and folder != "%s-%s" % (sid, slug):
                errs.append("folder '%s' does not match storyId-slug '%s-%s'" % (folder, sid, slug))
            if isinstance(sid, str):
                by_story.setdefault(sid, []).append(folder)
        results.append({"file": p, "errors": errs})
    by_file = {r["file"]: r for r in results}
    for sid, folders in sorted(by_story.items()):
        if len(folders) > 1:
            msg = "duplicate storyId '%s' in folders %s" % (sid, ", ".join(folders))
            for p in paths:
                if os.path.basename(os.path.dirname(p)) in folders:
                    by_file[p]["errors"].append(msg)
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate impact.json records.")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--all", action="store_true", help="validate every impacts/*/impact.json as promoted")
    ap.add_argument("--stage", choices=("draft", "promoted"), default="draft")
    ap.add_argument("--check-evidence", action="store_true")
    ap.add_argument("--root", default=ROOT)
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if args.all == bool(args.files):
        print("usage: give either <file>... or --all", file=sys.stderr)
        return 2
    if args.all:
        results = _run_all(args.root)
    else:
        results = _run_files(args.files, args.stage, args.root, args.check_evidence)
    ok = all(not r["errors"] for r in results)
    print(json.dumps({"ok": ok, "results": results}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
