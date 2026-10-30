#!/usr/bin/env python3
"""Run a skill's eval cases against a produced output and apply the deterministic assertions.

This runner does not call a model. It takes the model's output (a markdown file) per case and checks it,
so it works identically under Claude Code, Copilot, Promptfoo, or `claude plugin eval`. Run each case
N times (default 5) by producing N outputs and passing them all; the case passes only if every run passes.

  python3 tools/evals/run_skill.py --skill story-impact --case 001-new-field-on-account \
      --output ai-context/9001-risk-rating-field/impact.md [--output ...]

Assertions supported in case JSON: must_reference, must_not_flag, must_flag, must_contain_label,
must_label_every_claim, banned_phrases, verdict_in, max_hops, impact_json_valid, must_flag_overlap,
story_json_valid, must_keep_edge, must_list_overlap, edges_from_seeds_only, seeds_accounted.
Every cited `path:line` must exist.

impact_json_valid: the impact.json beside each --output validates as a draft, evidence checked.
must_flag_overlap: each api is the exact backticked Component cell of a row in the table under
`## Overlaps with other stories`. Rows in that table carry no confidence label and are skipped by
must_label_every_claim.

story-refine assertions (story_json_valid, must_keep_edge, must_list_overlap,
edges_from_seeds_only, seeds_accounted). A seed is identified by (component, category, detail).
story_json_valid: the story.json beside each --output passes validate_story as a draft, evidence
checked, and check_ac has no findings.
must_keep_edge: each name matches an edgeCases row of that story.json whose triple is a seed in
scan/edge-seeds.json: the name equals the row's component, or appears as a whole word in its detail.
must_list_overlap: as must_flag_overlap, for story.md.
edges_from_seeds_only: every edgeCases triple of that story.json is in the `seeds` list of
scan/edge-seeds.json beside --output (the query.py edge-seeds output the skill saved), with the
seed's evidence and confidence copied unchanged.
seeds_accounted: every seed in scan/edge-seeds.json is an edgeCases or droppedSeeds triple.
For these three, a missing story.json or edge-seeds.json fails.
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "stories"))
sys.path.insert(0, os.path.join(ROOT, "tools", "impacts"))

from validate import validate  # noqa: E402
from validate_story import validate_story  # noqa: E402
from check_ac import check_ac, load_vague  # noqa: E402

LABELS = ("Confirmed", "Inferred", "Unverifiable")
EVIDENCE_RE = re.compile(r"`((?:force-app|pkg-[A-Za-z0-9_-]+|fixtures|demo)/[^`:]+):(\d+)`")
OVERLAP_HEADING = "## Overlaps with other stories"
BACKTICKED_RE = re.compile(r"^`([^`]*)`$")


def overlap_line_numbers(output_text):
    """Indices of the lines under the Overlaps heading, up to the next # heading."""
    lines = output_text.splitlines()
    inside, found = False, set()
    for i, line in enumerate(lines):
        if line.strip() == OVERLAP_HEADING:
            inside = True
            continue
        if inside and line.lstrip().startswith("#"):
            inside = False
        if inside:
            found.add(i)
    return found


def overlap_components(output_text):
    """Backticked first-cell text of each row in the Overlaps table."""
    lines = output_text.splitlines()
    apis = set()
    for i in overlap_line_numbers(output_text):
        line = lines[i].strip()
        if not line.startswith("|"):
            continue
        cells = line.split("|")
        if len(cells) < 3:
            continue
        m = BACKTICKED_RE.match(cells[1].strip())
        if m:
            apis.add(m.group(1))
    return apis


def check_impact_json(output_path):
    if not output_path:
        return ["impact_json_valid: no output path to locate impact.json"]
    path = os.path.join(os.path.dirname(output_path), "impact.json")
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        return [f"impact.json unreadable at {path}: {exc}"]
    return [f"impact.json invalid: {e}" for e in validate(doc, "draft", ROOT, check_evidence=True)]


def load_sibling(output_path, rel, name):
    """(parsed JSON of <dir of output>/<rel>, None) or (None, failure text)."""
    if not output_path:
        return None, f"{name}: no output path to locate {rel}"
    path = os.path.join(os.path.dirname(output_path), rel)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, ValueError) as exc:
        return None, f"{rel} unreadable at {path}: {exc}"


def story_edge_cases(doc):
    ecs = doc.get("edgeCases") if isinstance(doc, dict) else None
    return [c for c in ecs if isinstance(c, dict)] if isinstance(ecs, list) else []


def check_story_json(output_path):
    doc, err = load_sibling(output_path, "story.json", "story_json_valid")
    if err:
        return [err]
    fails = [f"story.json invalid: {e}" for e in validate_story(doc, "draft", ROOT, check_evidence=True)]
    if isinstance(doc, dict):
        fails += [f"story.json criterion {f['id']}: {f['rule']}: {f['detail']}"
                  for f in check_ac(doc, load_vague())]
    return fails


def triple(row):
    """A seed's identity: (component, category, detail)."""
    return (row.get("component"), row.get("category"), row.get("detail"))


def fmt(t):
    return "(%s, %s, %s)" % t


def edge_matches(ec, name):
    """name equals the row's component, or appears as a whole word in its detail."""
    if ec.get("component") == name:
        return True
    detail = ec.get("detail")
    return isinstance(detail, str) and re.search(
        r"(?<!\w)" + re.escape(name) + r"(?!\w)", detail) is not None


def seed_index(rows):
    """triple -> {(evidence, confidence)} over the scan's seeds."""
    index = {}
    for s in rows:
        index.setdefault(triple(s), set()).add((s.get("evidence"), s.get("confidence")))
    return index


def check_keep_edge(output_path, wanted):
    """Only edge cases that are real seeds (triple in scan/edge-seeds.json) count."""
    doc, rows, fails = load_seed_rows(output_path, "must_keep_edge")
    if fails:
        return fails
    known = seed_index(rows)
    ecs = [ec for ec in story_edge_cases(doc) if triple(ec) in known]
    return [f"edge case not kept for {w}" for w in wanted if not any(edge_matches(ec, w) for ec in ecs)]


def load_seed_rows(output_path, name):
    """(story doc, seed rows, []) or (None, None, [failure])."""
    doc, err = load_sibling(output_path, "story.json", name)
    if err:
        return None, None, [err]
    seeds, err = load_sibling(output_path, "scan/edge-seeds.json", name)
    if err:
        return None, None, [err]
    rows = seeds.get("seeds") if isinstance(seeds, dict) else None
    if not isinstance(rows, list):
        return None, None, ["scan/edge-seeds.json has no seeds list"]
    return doc, [s for s in rows if isinstance(s, dict)], []


def check_edges_from_seeds(output_path):
    doc, rows, fails = load_seed_rows(output_path, "edges_from_seeds_only")
    if fails:
        return fails
    known = seed_index(rows)
    fails = []
    for ec in story_edge_cases(doc):
        t = triple(ec)
        if t not in known:
            fails.append(f"edge case {ec.get('id')} {fmt(t)} is not in scan/edge-seeds.json")
        elif (ec.get("evidence"), ec.get("confidence")) not in known[t]:
            fails.append(f"edge case {ec.get('id')} {fmt(t)}: evidence {ec.get('evidence')!r} and "
                         f"confidence {ec.get('confidence')!r} differ from the seed's")
    return fails


def check_seeds_accounted(output_path):
    doc, rows, fails = load_seed_rows(output_path, "seeds_accounted")
    if fails:
        return fails
    dropped = doc.get("droppedSeeds") if isinstance(doc, dict) else None
    dropped = [d for d in dropped if isinstance(d, dict)] if isinstance(dropped, list) else []
    seen = {triple(r) for r in story_edge_cases(doc) + dropped}
    return [f"seed {fmt(triple(s))} is neither an edge case nor a dropped seed"
            for s in rows if triple(s) not in seen]


def check(output_text, asserts, output_path=None):
    fails = []
    for ref in asserts.get("must_reference", []):
        if ref not in output_text:
            fails.append(f"missing reference {ref}")
    for ref in asserts.get("must_flag", []):
        if ref not in output_text:
            fails.append(f"did not flag {ref}")
    for ref in asserts.get("must_not_flag", []):
        if re.search(rf"\|[^\n]*{re.escape(ref)}[^\n]*\|", output_text) and "invented" in output_text.lower():
            fails.append(f"wrongly flagged {ref}")
    lbl = asserts.get("must_contain_label")
    if lbl and lbl not in output_text:
        fails.append(f"missing label {lbl}")
    for p in asserts.get("banned_phrases", []):
        if re.search(re.escape(p), output_text, re.I):
            fails.append(f"banned phrase present: {p!r}")
    if asserts.get("verdict_in"):
        if not any(v in output_text for v in asserts["verdict_in"]):
            fails.append(f"verdict not in {asserts['verdict_in']}")
    if asserts.get("must_label_every_claim"):
        skip = overlap_line_numbers(output_text)
        rows = [l for i, l in enumerate(output_text.splitlines())
                if i not in skip and l.startswith("| `") and "Evidence" not in l]
        unlabelled = [l for l in rows if not any(x in l for x in LABELS)]
        if unlabelled:
            fails.append(f"{len(unlabelled)} table row(s) without a confidence label")
    for path, line in EVIDENCE_RE.findall(output_text):
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            fails.append(f"evidence path does not exist: {path}")
        else:
            with open(full, encoding="utf-8", errors="replace") as fh:
                n = sum(1 for _ in fh)
            if int(line) > n:
                fails.append(f"evidence line {line} beyond end of {path} ({n} lines)")
    if asserts.get("max_hops"):
        for m in re.finditer(r"\|\s*(\d+)\s*\|\s*`[^`]*:\d+`", output_text):
            if int(m.group(1)) > asserts["max_hops"]:
                fails.append(f"hop {m.group(1)} exceeds max_hops {asserts['max_hops']}")
    if asserts.get("impact_json_valid"):
        fails += check_impact_json(output_path)
    flagged = overlap_components(output_text) if asserts.get("must_flag_overlap") else set()
    for api in asserts.get("must_flag_overlap", []):
        if api not in flagged:
            fails.append(f"overlap not flagged for {api}")
    if asserts.get("story_json_valid"):
        fails += check_story_json(output_path)
    if asserts.get("must_keep_edge"):
        fails += check_keep_edge(output_path, asserts["must_keep_edge"])
    listed = overlap_components(output_text) if asserts.get("must_list_overlap") else set()
    for api in asserts.get("must_list_overlap", []):
        if api not in listed:
            fails.append(f"overlap not listed for {api}")
    if asserts.get("edges_from_seeds_only"):
        fails += check_edges_from_seeds(output_path)
    if asserts.get("seeds_accounted"):
        fails += check_seeds_accounted(output_path)
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--case", required=True)
    ap.add_argument("--output", action="append", required=True)
    a = ap.parse_args()
    case_path = os.path.join(ROOT, "framework", "skills", a.skill, "evals", "cases", a.case + ".json")
    with open(case_path) as fh:
        case = json.load(fh)
    all_ok = True
    for i, out in enumerate(a.output, 1):
        with open(out, encoding="utf-8") as fh:
            txt = fh.read()
        fails = check(txt, case["assert"], out)
        ok = not fails
        all_ok &= ok
        print(f"run {i}: {'PASS' if ok else 'FAIL'}")
        for f in fails:
            print("   - " + f)
    print(f"\ncase {a.case}: {'PASS' if all_ok else 'FAIL'} over {len(a.output)} run(s)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
