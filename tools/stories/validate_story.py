#!/usr/bin/env python3
"""Validate story.json records.

Usage:
  validate_story.py <file>... [--stage draft|confirmed] [--check-evidence] [--root .]
  validate_story.py --all [--root .]

--all validates every <root>/impacts/*/story.json as confirmed, checks that each
folder is named <storyId>-<slug>, and that storyIds are unique.

Prints JSON on stdout. Exit codes: 0 valid, 1 validation failure, 2 bad usage.
Stdlib only. Code comes from the checkout; data comes from --root.
"""
import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "impacts"))

import validate as V  # noqa: E402  (tools/impacts/validate.py, reused, not copied)

# Edge-seed categories emitted by tools/index/query.py edge_seeds (query.py exposes no tuple).
CATEGORIES = ("blank", "picklist-value", "field-access", "record-type", "automation",
              "bulk", "integration-user")
CONFIDENCE = ("Confirmed", "Inferred", "Unverifiable")
AC_SOURCES = ("stated", "edge-case", "assistant-proposed")
STATUSES = ("draft", "confirmed")
OVERLAP_KINDS = ("conflict", "watch")

TOP_REQUIRED = ("schemaVersion", "storyId", "slug", "status", "squad", "persona", "goal",
                "benefit", "inScope", "outOfScope", "nonFunctional", "openQuestions",
                "acceptanceCriteria", "edgeCases", "droppedSeeds", "overlaps", "seeds")
TOP_ALLOWED = TOP_REQUIRED + ("confirmedBy",)
AC_KEYS = ("id", "given", "when", "then", "examples", "source")
EC_KEYS = ("id", "category", "component", "evidence", "confidence", "becameCriterion", "reason")
DS_KEYS = ("category", "component", "reason")
OQ_KEYS = ("id", "text", "ownerRole", "answer", "deferred")
OV_KEYS = ("api", "type", "kind", "stories")
OV_STORY_KEYS = ("storyId", "squad", "status", "changeType", "type", "commit")


def _nonempty(v):
    return isinstance(v, str) and v.strip() != ""


def _keys(tag, obj, allowed, errors):
    """Exact-key check: every allowed key present, no other key."""
    for k in obj:
        if k not in allowed:
            errors.append("%s: unknown key '%s'" % (tag, k))
    for k in allowed:
        if k not in obj:
            errors.append("%s: missing key '%s'" % (tag, k))


def _ids(tag, items, prefix, errors):
    """Ids are PREFIX-n, unique, numbered 1..n with no gaps."""
    pat = re.compile(re.escape(prefix) + r"-([1-9][0-9]*)")
    nums = []
    for i, it in enumerate(items):
        v = it.get("id") if isinstance(it, dict) else None
        m = pat.fullmatch(v) if isinstance(v, str) else None
        if not m:
            errors.append("%s[%d]: id '%s' does not match %s-<n>" % (tag, i, v, prefix))
            continue
        if int(m.group(1)) in nums:
            errors.append("%s[%d]: duplicate id '%s'" % (tag, i, v))
        nums.append(int(m.group(1)))
    expected = set(range(1, len(items) + 1))
    if nums and set(nums) != expected and len(set(nums)) == len(nums) and len(nums) == len(items):
        errors.append("%s: ids %s have gaps; expected %s-1 to %s-%d"
                      % (tag, ", ".join("%s-%d" % (prefix, n) for n in sorted(nums)),
                         prefix, prefix, len(items)))
    return {"%s-%d" % (prefix, n) for n in nums}


def _str_list(doc, key, errors):
    if key in doc:
        v = doc[key]
        if not isinstance(v, list) or not all(isinstance(s, str) for s in v):
            errors.append("%s is not a list of strings" % key)


def _obj_list(doc, key, errors):
    """Return the list when doc[key] is a list, else record an error and return None."""
    if key not in doc:
        return None
    if not isinstance(doc[key], list):
        errors.append("%s is not a list" % key)
        return None
    return doc[key]


def _check_ac(items, errors):
    for i, a in enumerate(items):
        tag = "acceptanceCriteria[%d]" % i
        if not isinstance(a, dict):
            errors.append("%s: not an object" % tag)
            continue
        _keys(tag, a, AC_KEYS, errors)
        for k in ("given", "when", "then"):
            if k in a and not isinstance(a[k], str):
                errors.append("%s: %s is not a string" % (tag, k))
        ex = a.get("examples")
        if "examples" in a and (not isinstance(ex, list) or not all(isinstance(s, str) for s in ex)):
            errors.append("%s: examples is not a list of strings" % tag)
        if "source" in a and a["source"] not in AC_SOURCES:
            errors.append("%s: source '%s' is not one of %s" % (tag, a["source"], ", ".join(AC_SOURCES)))


def _check_ec(items, ac_ids, root, check_evidence, errors):
    for i, c in enumerate(items):
        tag = "edgeCases[%d]" % i
        if not isinstance(c, dict):
            errors.append("%s: not an object" % tag)
            continue
        _keys(tag, c, EC_KEYS, errors)
        if "category" in c and c["category"] not in CATEGORIES:
            errors.append("%s: category '%s' is not one of %s" % (tag, c["category"], ", ".join(CATEGORIES)))
        if "component" in c and not _nonempty(c["component"]):
            errors.append("%s: component is not a non-empty string" % tag)
        if "confidence" in c and c["confidence"] not in CONFIDENCE:
            errors.append("%s: confidence '%s' is not one of %s" % (tag, c["confidence"], ", ".join(CONFIDENCE)))
        if "evidence" in c:
            ev = c["evidence"]
            if ev is None:
                if c.get("confidence") != "Unverifiable":
                    errors.append("%s: evidence is null; allowed only for confidence Unverifiable" % tag)
            else:
                parsed = V.split_evidence(ev)
                if parsed is None:
                    errors.append("%s: evidence '%s' is not 'path:line' with an integer line >= 1"
                                  % (tag, ev))
                elif check_evidence:
                    problem = V.check_evidence_file(root, parsed[0], parsed[1])
                    if problem:
                        errors.append("%s: evidence '%s': %s" % (tag, ev, problem))
        if "becameCriterion" in c and "reason" in c:
            bc, reason = c["becameCriterion"], c["reason"]
            if bc is None:
                if not _nonempty(reason):
                    errors.append("%s: reason is required when becameCriterion is null" % tag)
            else:
                if not (isinstance(bc, str) and bc in ac_ids):
                    errors.append("%s: becameCriterion '%s' is not an acceptance criterion id" % (tag, bc))
                if reason is not None:
                    errors.append("%s: reason is present but becameCriterion is not null" % tag)


def _check_dropped(items, errors):
    for i, d in enumerate(items):
        tag = "droppedSeeds[%d]" % i
        if not isinstance(d, dict):
            errors.append("%s: not an object" % tag)
            continue
        _keys(tag, d, DS_KEYS, errors)
        if "category" in d and d["category"] not in CATEGORIES:
            errors.append("%s: category '%s' is not one of %s" % (tag, d["category"], ", ".join(CATEGORIES)))
        for k in ("component", "reason"):
            if k in d and not _nonempty(d[k]):
                errors.append("%s: %s is not a non-empty string" % (tag, k))


def _check_questions(items, stage, errors):
    for i, q in enumerate(items):
        tag = "openQuestions[%d]" % i
        if not isinstance(q, dict):
            errors.append("%s: not an object" % tag)
            continue
        _keys(tag, q, OQ_KEYS, errors)
        for k in ("text", "ownerRole"):
            if k in q and not _nonempty(q[k]):
                errors.append("%s: %s is not a non-empty string" % (tag, k))
        if "answer" in q and q["answer"] is not None and not isinstance(q["answer"], str):
            errors.append("%s: answer is not a string or null" % tag)
        if "deferred" in q and not isinstance(q["deferred"], bool):
            errors.append("%s: deferred is not true or false" % tag)
        if stage == "confirmed" and "answer" in q and "deferred" in q:
            if not _nonempty(q["answer"]) and q["deferred"] is not True:
                errors.append("%s: not answered and not deferred" % tag)


def _check_overlaps(items, errors):
    for i, o in enumerate(items):
        tag = "overlaps[%d]" % i
        if not isinstance(o, dict):
            errors.append("%s: not an object" % tag)
            continue
        _keys(tag, o, OV_KEYS, errors)
        for k in ("api", "type"):
            if k in o and not _nonempty(o[k]):
                errors.append("%s: %s is not a non-empty string" % (tag, k))
        if "kind" in o and o["kind"] not in OVERLAP_KINDS:
            errors.append("%s: kind '%s' is not one of %s" % (tag, o["kind"], ", ".join(OVERLAP_KINDS)))
        stories = o.get("stories")
        if "stories" in o:
            if not isinstance(stories, list):
                errors.append("%s: stories is not a list" % tag)
                continue
            for j, s in enumerate(stories):
                stag = "%s.stories[%d]" % (tag, j)
                if not isinstance(s, dict):
                    errors.append("%s: not an object" % stag)
                    continue
                _keys(stag, s, OV_STORY_KEYS, errors)
                for k in OV_STORY_KEYS:
                    if k in s and not _nonempty(s[k]):
                        errors.append("%s: %s is not a non-empty string" % (stag, k))


def validate_story(doc, stage, root, check_evidence=False):
    """Return a list of error strings; empty when the story is valid."""
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

    if "squad" in doc:
        if not _nonempty(doc["squad"]):
            errors.append("squad is not a non-empty string")
        else:
            try:
                squads = V.load_squads(root)
            except (ValueError, OSError) as exc:
                errors.append("squad list unreadable: %s" % exc)
                squads = None
            if squads is not None and doc["squad"] not in squads:
                errors.append("squad '%s' is not listed in impacts/squads.json" % doc["squad"])

    if "status" in doc:
        st = doc["status"]
        if st not in STATUSES:
            errors.append("status '%s' is not one of %s" % (st, ", ".join(STATUSES)))
        elif st != stage:
            errors.append("status '%s': a %s story has status %s" % (st, stage, stage))

    if "confirmedBy" in doc:
        if stage == "draft":
            errors.append("confirmedBy is present in a draft story")
        elif not _nonempty(doc["confirmedBy"]):
            errors.append("confirmedBy is empty")
    elif stage == "confirmed":
        errors.append("confirmedBy is missing from a confirmed story")

    for k in ("persona", "goal", "benefit"):
        if k in doc and not _nonempty(doc[k]):
            errors.append("%s is not a non-empty string" % k)
    for k in ("inScope", "outOfScope", "nonFunctional", "seeds"):
        _str_list(doc, k, errors)

    acs = _obj_list(doc, "acceptanceCriteria", errors)
    ac_ids = set()
    if acs is not None:
        _check_ac(acs, errors)
        ac_ids = _ids("acceptanceCriteria", acs, "AC", errors)
    ecs = _obj_list(doc, "edgeCases", errors)
    if ecs is not None:
        _ids("edgeCases", ecs, "EC", errors)
        _check_ec(ecs, ac_ids, root, check_evidence, errors)
    dropped = _obj_list(doc, "droppedSeeds", errors)
    if dropped is not None:
        _check_dropped(dropped, errors)
    oqs = _obj_list(doc, "openQuestions", errors)
    if oqs is not None:
        _ids("openQuestions", oqs, "OQ", errors)
        _check_questions(oqs, stage, errors)
    ovs = _obj_list(doc, "overlaps", errors)
    if ovs is not None:
        _check_overlaps(ovs, errors)
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
        errs = [err] if err else validate_story(doc, stage, root, check_evidence)
        results.append({"file": f, "errors": errs})
    return results


def _run_all(root):
    results, by_story = [], {}
    paths = sorted(glob.glob(os.path.join(root, "impacts", "*", "story.json")))
    for p in paths:
        folder = os.path.basename(os.path.dirname(p))
        doc, err = _load_json(p)
        errs = [err] if err else validate_story(doc, "confirmed", root)
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
    ap = argparse.ArgumentParser(description="Validate story.json records.")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--all", action="store_true", help="validate every impacts/*/story.json as confirmed")
    ap.add_argument("--stage", choices=STATUSES, default=None)
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
    if args.all:
        results = _run_all(args.root)
    else:
        results = _run_files(args.files, args.stage or "draft", args.root, args.check_evidence)
    ok = all(not r["errors"] for r in results)
    print(json.dumps({"ok": ok, "results": results}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
