#!/usr/bin/env python3
"""Compare N run folders of one eval case on the must-agree fields. Reads files only.

Usage:
  python3 tools/evals/consistency.py <dir>... [--diff-names <file>...] [--text]

Each <dir> holds exactly one structured output, directly inside it, which sets the kind:
  impact.json  (story-impact)     components, componentRatings, evidence, decisions
  story.json   (story-refine)     keptEdgeSeeds, overlapApis
  design.json  (solution-design)  recommendedComponents, doNothingPresent
  change.json  (implement-story)  filesTouched, checksPass, criteriaToTests
Other files (run.json, *.md, scan/, captured stdout) are ignored.

Fields, each compared as a canonical value (sets are sorted lists, so order never counts as drift):
- impact: components is the api set; componentRatings is the sorted [api, impact, confidence]
  list; evidence is the set of non-null component evidence strings (path:line); decisions is the
  sorted [ownerRole, text] list. Decision text is compared verbatim, with no fuzzy matching.
- story: keptEdgeSeeds is the set of edgeCases triples [component, category, detail] (the seed
  identity run_skill.py uses); overlapApis is the set of overlaps[].api. Criterion wording is not
  compared.
- design: recommendedComponents is the api set of the option whose id equals
  recommendation.optionId (compared by set, never by option id, title or order; null when the id
  names no option); doNothingPresent is true when an option has doNothing true.
- change: filesTouched comes from the --diff-names file for that run, never from change.json
  (change.json is the session's own account). checksPass is true when done is a non-empty list and
  every exit is the integer 0. criteriaToTests is each criterion id with its tests sorted.

--diff-names: one file per run, paired with the dirs by position (the flag repeats, or takes several
files). Each file holds one path per line, as `git diff --name-only` plus untracked files print them;
blank lines are skipped, backslashes become "/", and duplicates collapse. Nothing is filtered: a path
that differs per run (for example a run folder under ai-context/) shows as drift, so leave such paths
out of the file.

A malformed record gives null for the field it breaks; that run then disagrees, and the exit stays 0.
A run folder with no structured output (the run never wrote or copied one) counts as a run whose
fields are all null, as long as another folder sets the kind.

Output: JSON {kind, runs, identical, fields: {name: {agree, values}}} with values in argument order.
runs is N; identical is k, the size of the largest group of runs whose fields are all equal.
--text prints the JSON, then a grid with one row per field and one column per run ("=" agrees with
the most common value, ties going to the earliest run; "x" differs), the full value of every
disagreeing field for each run, and a last line "k/N identical".

Exit codes: 0 always after a comparison (it reports, it never gates); 2 for bad usage, a missing or
unreadable folder or file, no folder with a structured output, a folder with several, or mixed kinds
across runs. Stdlib only. Output is byte-identical for the same inputs.
"""
import argparse
import json
import os
import sys

KIND_FILES = (("impact", "impact.json"), ("story", "story.json"), ("design", "design.json"),
              ("change", "change.json"))
FIELDS = {
    "impact": ("components", "componentRatings", "evidence", "decisions"),
    "story": ("keptEdgeSeeds", "overlapApis"),
    "design": ("recommendedComponents", "doNothingPresent"),
    "change": ("filesTouched", "checksPass", "criteriaToTests"),
}


class Usage(Exception):
    """Bad usage or unreadable input (exit 2)."""


def canon(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True)


def sorted_unique(items):
    """Sorted list of distinct JSON-able items, ordered by their canonical JSON."""
    seen = {}
    for it in items:
        seen.setdefault(canon(it), it)
    return [seen[k] for k in sorted(seen)]


def _dicts(value):
    """The dict items of a list, or None when value is not a list."""
    if not isinstance(value, list):
        return None
    return [v for v in value if isinstance(v, dict)]


# ---- extractors: each returns a canonical value, or None when the record is malformed ----

def impact_fields(doc):
    comps = _dicts(doc.get("components")) if isinstance(doc, dict) else None
    decs = _dicts(doc.get("decisions")) if isinstance(doc, dict) else None
    out = {}
    if comps is None:
        out.update({"components": None, "componentRatings": None, "evidence": None})
    else:
        out["components"] = sorted_unique(c.get("api") for c in comps)
        out["componentRatings"] = sorted_unique([c.get("api"), c.get("impact"), c.get("confidence")]
                                                for c in comps)
        out["evidence"] = sorted_unique(c.get("evidence") for c in comps if c.get("evidence") is not None)
    out["decisions"] = None if decs is None else sorted_unique([d.get("ownerRole"), d.get("text")]
                                                               for d in decs)
    return out


def story_fields(doc):
    ecs = _dicts(doc.get("edgeCases")) if isinstance(doc, dict) else None
    ovs = _dicts(doc.get("overlaps")) if isinstance(doc, dict) else None
    return {
        "keptEdgeSeeds": None if ecs is None else sorted_unique(
            [c.get("component"), c.get("category"), c.get("detail")] for c in ecs),
        "overlapApis": None if ovs is None else sorted_unique(o.get("api") for o in ovs),
    }


def design_fields(doc):
    opts = _dicts(doc.get("options")) if isinstance(doc, dict) else None
    rec = doc.get("recommendation") if isinstance(doc, dict) else None
    rec_id = rec.get("optionId") if isinstance(rec, dict) else None
    recommended = None
    if opts is not None and rec_id is not None:
        for o in opts:
            if o.get("id") == rec_id:
                comps = _dicts(o.get("components"))
                recommended = None if comps is None else sorted_unique(c.get("api") for c in comps)
                break
    return {
        "recommendedComponents": recommended,
        "doNothingPresent": None if opts is None else any(o.get("doNothing") is True for o in opts),
    }


def change_fields(doc, diff_lines):
    done = doc.get("done") if isinstance(doc, dict) else None
    c2t = doc.get("criteriaToTests") if isinstance(doc, dict) else None
    checks = None
    if isinstance(done, list):
        checks = bool(done) and all(isinstance(d, dict) and type(d.get("exit")) is int and d["exit"] == 0
                                    for d in done)
    mapping = None
    if isinstance(c2t, dict):
        mapping = {str(k): (sorted_unique(v) if isinstance(v, list) else None) for k, v in c2t.items()}
    files = sorted_unique(line.strip().replace("\\", "/") for line in diff_lines if line.strip())
    return {"filesTouched": files, "checksPass": checks, "criteriaToTests": mapping}


# ---- reading ----

def _read_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError, RecursionError) as exc:
        raise Usage("cannot read JSON %s: %s" % (path, type(exc).__name__))


def detect_kind(d):
    if not os.path.isdir(d):
        raise Usage("%s is not a folder" % d)
    found = [(kind, name) for kind, name in KIND_FILES if os.path.isfile(os.path.join(d, name))]
    if not found:
        return None
    if len(found) > 1:
        raise Usage("%s holds several structured outputs (%s); one per run folder"
                    % (d, ", ".join(n for _, n in found)))
    return found[0]


def _read_lines(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise Usage("cannot read diff names %s: %s" % (path, type(exc).__name__))


def compare(dirs, diff_names=None):
    """The comparison dict for run folders dirs (and, for change, one diff-names file per run)."""
    kinds = [detect_kind(d) for d in dirs]
    names = sorted({k[0] for k in kinds if k})
    if not names:
        raise Usage("no run folder holds any of %s" % ", ".join(n for _, n in KIND_FILES))
    if len(names) > 1:
        raise Usage("mixed kinds across runs: %s" % ", ".join(
            "%s=%s" % (d, k[0] if k else "none") for d, k in zip(dirs, kinds)))
    kind = names[0]
    diff_names = diff_names or []
    if kind == "change":
        if len(diff_names) != len(dirs):
            raise Usage("change runs take one --diff-names file per folder (%d folders, %d files)"
                        % (len(dirs), len(diff_names)))
    elif diff_names:
        raise Usage("--diff-names applies to change runs only; these runs are %s" % kind)
    per_run = []
    for i, (d, found) in enumerate(zip(dirs, kinds)):
        if found is None:  # the run left no structured output: every field is null (drift)
            per_run.append({name: None for name in FIELDS[kind]})
            continue
        doc = _read_json(os.path.join(d, found[1]))
        if kind == "impact":
            per_run.append(impact_fields(doc))
        elif kind == "story":
            per_run.append(story_fields(doc))
        elif kind == "design":
            per_run.append(design_fields(doc))
        else:
            per_run.append(change_fields(doc, _read_lines(diff_names[i])))
    fields = {}
    for name in FIELDS[kind]:
        values = [r[name] for r in per_run]
        fields[name] = {"agree": len({canon(v) for v in values}) == 1, "values": values}
    sigs = [canon([r[n] for n in FIELDS[kind]]) for r in per_run]
    identical = max(sigs.count(s) for s in sigs)
    return {"kind": kind, "runs": len(dirs), "identical": identical, "fields": fields}


# ---- text grid ----

def reference(values):
    """Canonical form of the most common value; ties go to the earliest run."""
    keys = [canon(v) for v in values]
    best = keys[0]
    for k in keys:
        if keys.count(k) > keys.count(best):
            best = k
    return best


def render_text(result, dirs):
    n = result["runs"]
    labels = ["run-%d" % i for i in range(1, n + 1)]
    names = list(result["fields"])
    width = max(len(x) for x in names + ["field"])
    lines = ["Kind: %s" % result["kind"], ""]
    lines += ["%s = %s" % (lab, d) for lab, d in zip(labels, dirs)]
    lines += ["", "  ".join(["field".ljust(width)] + labels + ["agree"])]
    for name in names:
        f = result["fields"][name]
        ref = reference(f["values"])
        marks = [("=" if canon(v) == ref else "x").ljust(len(lab)) for v, lab in zip(f["values"], labels)]
        lines.append("  ".join([name.ljust(width)] + marks + ["yes" if f["agree"] else "no"]))
    drifted = [name for name in names if not result["fields"][name]["agree"]]
    if drifted:
        lines += ["", "Disagreements:"]
        for name in drifted:
            lines.append("  %s" % name)
            for lab, v in zip(labels, result["fields"][name]["values"]):
                lines.append("    %s: %s" % (lab, canon(v)))
    lines += ["", "%d/%d identical" % (result["identical"], n)]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compare eval run folders on the must-agree fields.",
                                 allow_abbrev=False)
    ap.add_argument("dirs", nargs="+", help="run folders, one per run")
    ap.add_argument("--diff-names", nargs="+", action="extend", default=None,
                    help="change runs: one file of touched paths per run folder, in the same order")
    ap.add_argument("--text", action="store_true", help="also print the agreement grid")
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        result = compare(a.dirs, a.diff_names)
    except Usage as exc:
        print(str(exc), file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True) + "\n")
    if a.text:
        sys.stdout.write("\n" + render_text(result, a.dirs) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
