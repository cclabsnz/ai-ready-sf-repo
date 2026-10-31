#!/usr/bin/env python3
"""Validate design.json records (solution-design options with one recommendation).

Usage:
  validate_design.py <file>... [--stage draft|confirmed] [--index <dir>] [--check-evidence] [--root .]
  validate_design.py --all [--index <dir>] [--root .]

Checks the schema, exactly one doNothing option (with no components), every other option listing
at least one component, between 2 and 4 options with ids OPT-1..OPT-n (unique, no gaps), a
recommendation naming an existing option with at least one non-empty reason, and null evidence on
every changeType "new" component. A non-new component with null evidence is allowed only at
confidence Unverifiable. A confirmed record carries confirmedBy and a chosenOption naming an option;
a draft carries neither.

With an index (--index, or idx= in validate_design()), every component whose changeType is not
"new" is a node in the index, its type equals the node's type, and its evidence path (before the
last colon) is the node's path, or under it for bundle nodes whose path is a folder. Null evidence
(Unverifiable) and nodes with no path (standard objects) skip the path check, never the type
check. A "new" component is not already a node, compared case-insensitively ("already exists;
use modify or review"). In <file> mode the index check runs only when --index is given.
--all validates every <root>/impacts/*/design.json as confirmed against --index (default
<checkout>/index), checks each folder is named <storyId>-<slug> and that storyIds are unique.
It looks for designs first and loads the index only when at least one exists, so a checkout with
no designs exits 0 without an index.

Prints JSON on stdout. Exit codes: 0 valid, 1 validation failure, 2 bad usage (including an
unreadable index). Stdlib only. Code comes from the checkout (located from __file__); data comes
from --root.
"""
import argparse
import glob
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "impacts"))
sys.path.insert(0, os.path.join(ROOT, "tools", "stories"))

import validate as V  # noqa: E402  (tools/impacts/validate.py, reused, not copied)
from validate_story import _ids, _keys, _nonempty  # noqa: E402  (tools/stories/validate_story.py)

_spec = importlib.util.spec_from_file_location("query", os.path.join(ROOT, "tools", "index", "query.py"))
query = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(query)

DEFAULT_INDEX = os.path.join(ROOT, "index")
STATUSES = ("draft", "confirmed")
CRITERIA = ("security", "governor-limits", "data-volume", "licence-fit", "maintainability", "reuse")
MIN_OPTIONS, MAX_OPTIONS = 2, 4

TOP_REQUIRED = ("schemaVersion", "storyId", "slug", "status", "options", "recommendation",
                "provenance")
TOP_ALLOWED = TOP_REQUIRED + ("confirmedBy", "chosenOption")
OPTION_KEYS = ("id", "title", "summary", "doNothing", "components", "tradeOffs", "impactSummary")
COMP_KEYS = ("api", "type", "changeType", "evidence", "confidence")
TRADE_KEYS = ("criterion", "note")
REC_KEYS = ("optionId", "reasons")
PROV_KEYS = ("indexStamp", "frameworkVersion", "model", "assistantVersion")
PROV_STRINGS = ("frameworkVersion", "model", "assistantVersion")


def _check_against_node(tag, c, node, errors):
    """Tie a non-new component to its index node: same type, and evidence in the node's file.

    The evidence path (before the last colon) equals the node's path, or starts with node path +
    "/" for bundle nodes whose path is a folder. Null evidence (Unverifiable) skips the path check
    but not the type check. A node with no path (standard objects) cannot anchor evidence, so the
    path check is skipped for it."""
    node = node if isinstance(node, dict) else {}
    ntype = node.get("type")
    if _nonempty(c.get("type")) and c["type"] != ntype:
        errors.append("%s: type '%s' differs from the index node type '%s' for '%s'"
                      % (tag, c["type"], ntype, c["api"]))
    npath = node.get("path")
    parsed = V.split_evidence(c.get("evidence"))
    if parsed is None or not _nonempty(npath):
        return
    epath = parsed[0]
    if epath != npath and not epath.startswith(npath.rstrip("/") + "/"):
        errors.append("%s: evidence '%s' is not in the index node's file '%s' for '%s'"
                      % (tag, c["evidence"], npath, c["api"]))


def _check_component(tag, c, root, idx, check_evidence, errors):
    if not isinstance(c, dict):
        errors.append("%s: not an object" % tag)
        return
    _keys(tag, c, COMP_KEYS, errors)
    for k in ("api", "type"):
        if k in c and not _nonempty(c[k]):
            errors.append("%s: %s is not a non-empty string" % (tag, k))
    for k, allowed in (("changeType", V.CHANGE_TYPES), ("confidence", V.LABELS)):
        if k in c and c[k] not in allowed:
            errors.append("%s: %s '%s' is not one of %s" % (tag, k, c[k], ", ".join(allowed)))
    ct = c.get("changeType")
    if "evidence" in c:
        ev = c["evidence"]
        if ct == "new":
            if ev is not None:
                errors.append("%s: changeType new carries evidence '%s'; a new component has null "
                              "evidence" % (tag, ev))
        elif ev is None:
            if c.get("confidence") != "Unverifiable":
                errors.append("%s: evidence is null; allowed only for changeType new or confidence "
                              "Unverifiable" % tag)
        else:
            parsed = V.split_evidence(ev)
            if parsed is None:
                errors.append("%s: evidence '%s' is not 'path:line' with an integer line >= 1" % (tag, ev))
            elif check_evidence:
                problem = V.check_evidence_file(root, parsed[0], parsed[1])
                if problem:
                    errors.append("%s: evidence '%s': %s" % (tag, ev, problem))
    if idx is not None and ct in V.CHANGE_TYPES and _nonempty(c.get("api")):
        nodes = idx.get("nodes") if isinstance(idx, dict) else None
        nodes = nodes if isinstance(nodes, dict) else {}
        if ct == "new":
            low = c["api"].lower()
            clash = sorted(k for k in nodes if isinstance(k, str) and k.lower() == low)
            if clash:
                errors.append("%s: '%s' (changeType new) already exists as index node '%s'; use "
                              "modify or review" % (tag, c["api"], clash[0]))
        elif c["api"] not in nodes:
            errors.append("%s: '%s' (changeType %s) is not a node in the index; zero hits for the "
                          "exact API name" % (tag, c["api"], ct))
        else:
            _check_against_node(tag, c, nodes[c["api"]], errors)


def _check_option(i, o, root, idx, check_evidence, errors):
    tag = "options[%d]" % i
    if not isinstance(o, dict):
        errors.append("%s: not an object" % tag)
        return
    _keys(tag, o, OPTION_KEYS, errors)
    for k in ("title", "summary", "impactSummary"):
        if k in o and not _nonempty(o[k]):
            errors.append("%s: %s is not a non-empty string" % (tag, k))
    if "doNothing" in o and not isinstance(o["doNothing"], bool):
        errors.append("%s: doNothing is not true or false" % tag)
    comps = o.get("components")
    if "components" in o:
        if not isinstance(comps, list):
            errors.append("%s: components is not a list" % tag)
        else:
            if o.get("doNothing") is True and comps:
                errors.append("%s: the do-nothing option has components; it lists none" % tag)
            if o.get("doNothing") is False and not comps:
                errors.append("%s: lists no components; every option except do-nothing lists at "
                              "least one" % tag)
            seen = set()
            for j, c in enumerate(comps):
                ctag = "%s.components[%d]" % (tag, j)
                _check_component(ctag, c, root, idx, check_evidence, errors)
                api = c.get("api") if isinstance(c, dict) else None
                if isinstance(api, str):
                    if api in seen:
                        errors.append("%s: duplicate api '%s' in this option" % (ctag, api))
                    seen.add(api)
    trades = o.get("tradeOffs")
    if "tradeOffs" in o:
        if not isinstance(trades, list):
            errors.append("%s: tradeOffs is not a list" % tag)
        elif not trades:
            errors.append("%s: tradeOffs is empty; each option names at least one trade-off" % tag)
        else:
            for j, t in enumerate(trades):
                ttag = "%s.tradeOffs[%d]" % (tag, j)
                if not isinstance(t, dict):
                    errors.append("%s: not an object" % ttag)
                    continue
                _keys(ttag, t, TRADE_KEYS, errors)
                if "criterion" in t and t["criterion"] not in CRITERIA:
                    errors.append("%s: criterion '%s' is not one of %s"
                                  % (ttag, t["criterion"], ", ".join(CRITERIA)))
                if "note" in t and not _nonempty(t["note"]):
                    errors.append("%s: note is not a non-empty string" % ttag)


def _check_provenance(prov, errors):
    if not isinstance(prov, dict):
        errors.append("provenance is not an object")
        return
    for k in prov:
        if k not in PROV_KEYS:
            errors.append("provenance: unknown key '%s'" % k)
    stamp = prov.get("indexStamp")
    if not isinstance(stamp, dict) or not _nonempty(stamp.get("commit")):
        errors.append("provenance.indexStamp is not an object with a commit string")
    for k in PROV_STRINGS:
        if not _nonempty(prov.get(k)):
            errors.append("provenance.%s is not a non-empty string" % k)


def validate_design(doc, stage, root, idx=None, check_evidence=False):
    """Return a list of error strings; empty when the design is valid.

    idx: a loaded index (tools/index/query.py load()); when given, every non-new component is a
    node in idx["nodes"]."""
    errors = []
    if stage not in STATUSES:
        return ["stage '%s' is not draft or confirmed" % stage]
    if not isinstance(doc, dict):
        return ["record is not a JSON object"]

    for k in doc:
        if k not in TOP_ALLOWED:
            errors.append("unknown top-level key '%s'" % k)
    for k in TOP_REQUIRED:
        if k not in doc:
            errors.append("missing top-level key '%s'" % k)

    if "schemaVersion" in doc and not (V.is_int(doc["schemaVersion"]) and doc["schemaVersion"] == 1):
        errors.append("schemaVersion is not 1")
    if "storyId" in doc and not (isinstance(doc["storyId"], str) and V.STORY_RE.fullmatch(doc["storyId"])):
        errors.append("storyId '%s' does not match %s" % (doc["storyId"], V.STORY_RE.pattern))
    if "slug" in doc and not (isinstance(doc["slug"], str) and V.SLUG_RE.fullmatch(doc["slug"])):
        errors.append("slug '%s' does not match %s" % (doc["slug"], V.SLUG_RE.pattern))

    if "status" in doc:
        st = doc["status"]
        if st not in STATUSES:
            errors.append("status '%s' is not one of %s" % (st, ", ".join(STATUSES)))
        elif st != stage:
            errors.append("status '%s': a %s design has status %s" % (st, stage, stage))

    if "provenance" in doc:
        _check_provenance(doc["provenance"], errors)

    option_ids = set()
    opts = doc.get("options")
    if "options" in doc:
        if not isinstance(opts, list):
            errors.append("options is not a list")
        else:
            if not MIN_OPTIONS <= len(opts) <= MAX_OPTIONS:
                errors.append("options: a design has between %d and %d options, including do-nothing"
                              % (MIN_OPTIONS, MAX_OPTIONS))
            option_ids = _ids("options", opts, "OPT", errors)
            for i, o in enumerate(opts):
                _check_option(i, o, root, idx, check_evidence, errors)
            dn = [o for o in opts if isinstance(o, dict) and o.get("doNothing") is True]
            if len(dn) != 1:
                errors.append("options: exactly one doNothing option is required; found %d" % len(dn))

    rec = doc.get("recommendation")
    if "recommendation" in doc:
        if not isinstance(rec, dict):
            errors.append("recommendation is not an object")
        else:
            _keys("recommendation", rec, REC_KEYS, errors)
            if "optionId" in rec and not (isinstance(rec["optionId"], str) and rec["optionId"] in option_ids):
                errors.append("recommendation.optionId '%s' is not an option id" % rec["optionId"])
            reasons = rec.get("reasons")
            if "reasons" in rec:
                if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
                    errors.append("recommendation.reasons is not a list of strings")
                elif not any(_nonempty(r) for r in reasons):
                    errors.append("recommendation.reasons has no non-empty reason")
                elif not all(_nonempty(r) for r in reasons):
                    errors.append("recommendation.reasons holds an empty reason")

    for k in ("confirmedBy", "chosenOption"):
        if k in doc:
            if stage == "draft":
                errors.append("%s is present in a draft design" % k)
            elif not _nonempty(doc[k]):
                errors.append("%s is empty" % k)
        elif stage == "confirmed":
            errors.append("%s is missing from a confirmed design" % k)
    if stage == "confirmed" and _nonempty(doc.get("chosenOption")) and doc["chosenOption"] not in option_ids:
        errors.append("chosenOption '%s' is not an option id" % doc["chosenOption"])
    return errors


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, ValueError) as exc:
        return None, "cannot read JSON: %s" % exc


def load_index(index_dir):
    """(idx, None) or (None, problem text)."""
    try:
        idx = query.load(index_dir)
    except (OSError, ValueError) as exc:
        return None, "cannot load index %s: %s" % (index_dir, exc)
    if not isinstance(idx, dict) or not isinstance(idx.get("nodes"), dict):
        return None, "index %s has no nodes object" % index_dir
    return idx, None


def _run_files(files, stage, root, idx, check_evidence):
    results = []
    for f in files:
        doc, err = _load_json(f)
        errs = [err] if err else validate_design(doc, stage, root, idx, check_evidence)
        results.append({"file": f, "errors": errs})
    return results


def _run_all(root, idx):
    results, by_story = [], {}
    paths = sorted(glob.glob(os.path.join(root, "impacts", "*", "design.json")))
    for p in paths:
        folder = os.path.basename(os.path.dirname(p))
        doc, err = _load_json(p)
        errs = [err] if err else validate_design(doc, "confirmed", root, idx)
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
    ap = argparse.ArgumentParser(description="Validate design.json records.")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--all", action="store_true", help="validate every impacts/*/design.json as confirmed")
    ap.add_argument("--stage", choices=STATUSES, default=None)
    ap.add_argument("--index", default=None,
                    help="index dir for the component check (default for --all: <checkout>/index)")
    ap.add_argument("--check-evidence", action="store_true")
    ap.add_argument("--root", default=ROOT)
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if args.all == bool(args.files):
        print("usage: give either <file>... or --all", file=sys.stderr)
        return 2
    if args.all and (args.stage is not None or args.check_evidence):
        print("usage: --all takes neither --stage nor --check-evidence", file=sys.stderr)
        return 2
    index_dir = args.index or (DEFAULT_INDEX if args.all else None)
    if args.all and not glob.glob(os.path.join(args.root, "impacts", "*", "design.json")):
        index_dir = None  # no designs on record: nothing to check, so the index is not needed
    idx = None
    if index_dir is not None:
        idx, err = load_index(index_dir)
        if err:
            print(err, file=sys.stderr)
            return 2
    if args.all:
        results = _run_all(args.root, idx)
    else:
        results = _run_files(args.files, args.stage or "draft", args.root, idx, args.check_evidence)
    ok = all(not r["errors"] for r in results)
    print(json.dumps({"ok": ok, "results": results}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
