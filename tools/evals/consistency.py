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
files). Each file holds one path per line, as `git diff --name-only` plus untracked files print them.
It is read as UTF-8 (a BOM is allowed) or as UTF-16 when it starts with a UTF-16 BOM; a file that
does not decode makes filesTouched invalid for that run. Blank lines are skipped, backslashes become
"/", and duplicates collapse. Nothing is filtered: a path that differs per run (for example a run
folder under ai-context/) shows as drift, so leave such paths out of the file.

Invalid values. A field is null ("invalid") when the run gives no usable value for it: the record is
missing (a run folder with no structured output, as long as another folder sets the kind), empty,
unparseable, too deeply nested, not an object, or malformed where that field is read. Null never
counts as agreement: a field with an invalid run has agree false, and a run with any invalid field
is never counted in identical. The comparison continues and the exit stays 0.

Output: JSON {kind, runs, identical, invalidRuns, fields: {name: {agree, invalidRuns, values}}} with
values in argument order and invalidRuns as 1-based run numbers. runs is N; identical is k, the size
of the largest group of valid runs (no invalid field) whose fields are all equal, 0 when no run is
valid. --text prints the JSON, then a grid with one row per field and one column per run ("=" agrees
with the most common valid value, ties going to the earliest run; "x" differs; "inv" is invalid),
the full value of every disagreeing field for each run, and a last line "k/N identical".

Exit codes: 0 after a comparison (it reports, it never gates); 2 for bad usage (a missing folder or
diff-names file, wrong --diff-names count, no folder with a structured output, a folder with
several) and for mixed kinds across runs. Stdlib only. Output is byte-identical for the same inputs.
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
    if isinstance(c2t, dict) and all(isinstance(v, list) for v in c2t.values()):
        mapping = {str(k): sorted_unique(v) for k, v in c2t.items()}
    files = None
    if diff_lines is not None:
        files = sorted_unique(line.strip().replace("\\", "/") for line in diff_lines if line.strip())
    return {"filesTouched": files, "checksPass": checks, "criteriaToTests": mapping}


# ---- reading ----

class Invalid(Exception):
    """A record that gives no usable value (the run counts as invalid)."""


def _read_json(path):
    """The parsed record, or Invalid when it is empty, unparseable, too deep or not an object."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError, RecursionError):
        raise Invalid(path)
    if not isinstance(doc, dict):
        raise Invalid(path)
    return doc


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
    """Lines of a diff-names file (UTF-8, optional BOM, or UTF-16 with a BOM); None when it does not
    decode. A missing or unreadable file is bad usage."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise Usage("cannot read diff names %s: %s" % (path, type(exc).__name__))
    try:
        if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
            text = data.decode("utf-16")
        else:
            text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    return text.splitlines()


def _valid(v):
    return v is not None


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
    lines = [_read_lines(p) for p in diff_names]  # bad paths are usage errors, checked up front
    per_run = []
    for i, (d, found) in enumerate(zip(dirs, kinds)):
        doc = None  # no structured output, or an unusable one: the record's fields are invalid
        if found is not None:
            try:
                doc = _read_json(os.path.join(d, found[1]))
            except Invalid:
                doc = None
        if kind == "change":  # filesTouched comes from the diff names even when the record is invalid
            row = change_fields(doc if doc is not None else {}, lines[i])
        elif doc is None:
            row = {name: None for name in FIELDS[kind]}
        else:
            row = {"impact": impact_fields, "story": story_fields, "design": design_fields}[kind](doc)
        per_run.append(row)
    fields = {}
    for name in FIELDS[kind]:
        values = [r[name] for r in per_run]
        invalid = [i for i, v in enumerate(values, 1) if not _valid(v)]
        fields[name] = {"agree": not invalid and len({canon(v) for v in values}) == 1,
                        "invalidRuns": invalid, "values": values}
    valid_sigs = [canon([r[n] for n in FIELDS[kind]]) for r in per_run
                  if all(_valid(r[n]) for n in FIELDS[kind])]
    identical = max((valid_sigs.count(s) for s in valid_sigs), default=0)
    invalid_runs = [i for i, r in enumerate(per_run, 1) if not all(_valid(r[n]) for n in FIELDS[kind])]
    return {"kind": kind, "runs": len(dirs), "identical": identical, "invalidRuns": invalid_runs,
            "fields": fields}


# ---- text grid ----

def reference(values):
    """Canonical form of the most common valid value; ties go to the earliest run. None when no
    value is valid."""
    keys = [canon(v) for v in values if _valid(v)]
    if not keys:
        return None
    best = keys[0]
    for k in keys:
        if keys.count(k) > keys.count(best):
            best = k
    return best


def mark(value, ref):
    if not _valid(value):
        return "inv"
    return "=" if canon(value) == ref else "x"


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
        marks = [mark(v, ref).ljust(len(lab)) for v, lab in zip(f["values"], labels)]
        lines.append("  ".join([name.ljust(width)] + marks + ["yes" if f["agree"] else "no"]))
    lines.append("(= matches the most common valid value, x differs, inv is invalid: no usable value)")
    drifted = [name for name in names if not result["fields"][name]["agree"]]
    if drifted:
        lines += ["", "Disagreements:"]
        for name in drifted:
            lines.append("  %s" % name)
            for lab, v in zip(labels, result["fields"][name]["values"]):
                lines.append("    %s: %s" % (lab, canon(v) if _valid(v) else "invalid"))
    if result["invalidRuns"]:
        lines += ["", "Invalid runs (never counted as identical): %s"
                  % ", ".join("run-%d" % i for i in result["invalidRuns"])]
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
