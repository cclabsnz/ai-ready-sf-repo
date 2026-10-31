#!/usr/bin/env python3
"""Validate impact.json records.

Usage:
  validate.py <file>... [--stage draft|promoted] [--check-evidence] [--root .]
  validate.py --all [--index <dir>] [--root .]

--all validates every <root>/impacts/*/impact.json as promoted, checks that each
folder is named <storyId>-<slug>, and that storyIds are unique. A design.json beside an
impact is validated as confirmed by tools/designs/validate_design.py against --index
(default <checkout>/index), and its chosenOption must equal the impact's. When that option is
the design's doNothing option, the impact has no new, modify or delete component. The index is
loaded only when a design exists; an unreadable index is exit 2.

Optional fields from solution-design (WS10): designOption (OPT-<n>, the option the record
assesses), provenance.recommendedBy ("assistant" when the assessed option was the assistant's
recommendation) and chosenOption (promoted records only; required there with designOption and
equal to it). Records without a design carry none of the three.

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
TOP_ALLOWED = TOP_REQUIRED + ("confirmedBy", "designOption", "chosenOption")
OPTION_RE = re.compile(r"^OPT-[1-9][0-9]*$")
RECOMMENDED_BY = ("assistant",)
DEFAULT_INDEX = os.path.join(ROOT, "index")
PROV_STRINGS = ("frameworkVersion", "model", "assistantVersion")
COMP_KEYS = ("api", "type", "changeType", "impact", "confidence", "hop", "evidence", "path")


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


_is_int = is_int


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


def check_evidence_file(root, path, line):
    """Return a problem string for an evidence path:line, or None when it checks out."""
    try:
        base = os.path.realpath(root)
        full = os.path.realpath(os.path.join(base, path))
        if full != base and not full.startswith(base + os.sep):
            return "resolves outside the root"
        if not os.path.isfile(full):
            return "file does not exist"
        with open(full, "rb") as fh:
            count = len(fh.read().splitlines())
    except (OSError, ValueError):
        return "evidence path unreadable: %r" % path
    if line > count:
        return "line %d is past the end of the file (%d lines)" % (line, count)
    return None


_check_evidence_file = check_evidence_file


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

    # A record sized from a solution-design option names it; WS2-era records carry none of these.
    for k in ("designOption", "chosenOption"):
        if k in doc and not (isinstance(doc[k], str) and OPTION_RE.match(doc[k])):
            errors.append("%s '%s' does not match OPT-<n>" % (k, doc[k]))
    if "chosenOption" in doc:
        if stage == "draft":
            errors.append("chosenOption is present in a draft record; promotion records it")
        elif doc.get("designOption") != doc["chosenOption"]:
            errors.append("chosenOption '%s' differs from designOption '%s'; the record assesses "
                          "the chosen option" % (doc["chosenOption"], doc.get("designOption")))
    elif stage == "promoted" and "designOption" in doc:
        errors.append("chosenOption is missing from a promoted record that names a designOption")

    prov = doc.get("provenance")
    if "provenance" in doc:
        if not isinstance(prov, dict):
            errors.append("provenance is not an object")
        else:
            if "recommendedBy" in prov:
                if prov["recommendedBy"] not in RECOMMENDED_BY:
                    errors.append("provenance.recommendedBy '%s' is not one of %s"
                                  % (prov["recommendedBy"], ", ".join(RECOMMENDED_BY)))
                if "designOption" not in doc:
                    errors.append("provenance.recommendedBy is present without a designOption")
            allowed = ("indexStamp", "hops", "recommendedBy") + PROV_STRINGS
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
    except (OSError, ValueError, RecursionError) as exc:
        return None, "cannot read JSON: %s" % exc


def _run_files(files, stage, root, check_evidence):
    results = []
    for f in files:
        doc, err = _load_json(f)
        errs = [err] if err else validate(doc, stage, root, check_evidence)
        results.append({"file": f, "errors": errs})
    return results


DO_NOTHING_MSG = "the chosen option is do nothing; the impact must not change components"
CHANGING_TYPES = ("new", "modify", "delete")


def do_nothing_conflict(impact, design, chosen):
    """Return the apis the impact changes (new, modify, delete) when `chosen` is the design's
    doNothing option; an empty list otherwise. review components are allowed."""
    opts = design.get("options") if isinstance(design, dict) else None
    opt = next((o for o in opts or [] if isinstance(o, dict) and o.get("id") == chosen), None)
    if not opt or opt.get("doNothing") is not True:
        return []
    comps = impact.get("components") if isinstance(impact, dict) else None
    return [c.get("api") for c in comps or []
            if isinstance(c, dict) and c.get("changeType") in CHANGING_TYPES]


def _design_module():
    """tools/designs/validate_design.py, imported only when a design is on record.

    Imported lazily: validate_design imports this module, so a top-level import would be circular.
    The path comes from this checkout (__file__), never from --root."""
    designs = os.path.join(ROOT, "tools", "designs")
    if designs not in sys.path:
        sys.path.insert(0, designs)
    import validate_design  # noqa: E402
    return validate_design


def _run_designs(root, impact_paths, index_dir):
    """Validate each design.json beside an impact.json as confirmed, against the index.

    Returns (results, problem). problem is the index load error text, or None. The index is
    loaded only when at least one design exists."""
    pairs = []
    for p in impact_paths:
        d = os.path.join(os.path.dirname(p), "design.json")
        if os.path.lexists(d):
            pairs.append((p, d))
    if not pairs:
        return [], None
    vd = _design_module()
    idx, problem = vd.load_index(index_dir)
    if problem:
        return [], problem
    results = []
    for impact_path, p in pairs:
        folder = os.path.basename(os.path.dirname(p))
        if os.path.islink(p):
            results.append({"file": p, "errors": ["design.json is a symlink"]})
            continue
        doc, err = _load_json(p)
        errs = [err] if err else vd.validate_design(doc, "confirmed", root, idx)
        if not err and isinstance(doc, dict):
            sid, slug = doc.get("storyId"), doc.get("slug")
            if isinstance(sid, str) and isinstance(slug, str) and folder != "%s-%s" % (sid, slug):
                errs.append("folder '%s' does not match storyId-slug '%s-%s'" % (folder, sid, slug))
            imp, ierr = _load_json(impact_path)
            if not ierr and isinstance(imp, dict) and imp.get("chosenOption") != doc.get("chosenOption"):
                errs.append("chosenOption '%s' differs from the impact's chosenOption '%s'"
                            % (doc.get("chosenOption"), imp.get("chosenOption")))
            if not ierr and isinstance(imp, dict):
                changed = do_nothing_conflict(imp, doc, doc.get("chosenOption"))
                if changed:
                    errs.append("%s (changes: %s)" % (DO_NOTHING_MSG, ", ".join(map(str, changed))))
        results.append({"file": p, "errors": errs})
    return results, None


def _run_all(root, index_dir=DEFAULT_INDEX):
    results = []
    by_story = {}
    paths = sorted(glob.glob(os.path.join(root, "impacts", "*", "impact.json")))
    design_results, problem = _run_designs(root, paths, index_dir)
    if problem:
        return None, problem
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
            if "chosenOption" in doc and not os.path.lexists(os.path.join(os.path.dirname(p), "design.json")):
                errs.append("chosenOption is set but no design.json is beside the impact")
        results.append({"file": p, "errors": errs})
    by_file = {r["file"]: r for r in results}
    for sid, folders in sorted(by_story.items()):
        if len(folders) > 1:
            msg = "duplicate storyId '%s' in folders %s" % (sid, ", ".join(folders))
            for p in paths:
                if os.path.basename(os.path.dirname(p)) in folders:
                    by_file[p]["errors"].append(msg)
    return results + design_results, None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate impact.json records.")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--all", action="store_true", help="validate every impacts/*/impact.json as promoted")
    ap.add_argument("--stage", choices=("draft", "promoted"), default=None)
    ap.add_argument("--check-evidence", action="store_true")
    ap.add_argument("--index", default=None,
                    help="index dir for designs beside impacts (--all only; default <checkout>/index)")
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
    if args.index is not None and not args.all:
        print("usage: --index applies only to --all", file=sys.stderr)
        return 2
    if args.all:
        results, problem = _run_all(args.root, args.index or DEFAULT_INDEX)
        if problem:
            print(problem, file=sys.stderr)
            return 2
    else:
        results = _run_files(args.files, args.stage or "draft", args.root, args.check_evidence)
    ok = all(not r["errors"] for r in results)
    print(json.dumps({"ok": ok, "results": results}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
