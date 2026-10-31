#!/usr/bin/env python3
"""Run a skill's eval cases against a produced output and apply the deterministic assertions.

This runner does not call a model. It takes the model's output (a markdown file) per case and checks it,
so it works identically under Claude Code, Copilot, Promptfoo, or `claude plugin eval`. Run each case
N times (default 5) by producing N outputs and passing them all; the case passes only if every run passes.

  python3 tools/evals/run_skill.py --skill story-impact --case 001-new-field-on-account \
      --output ai-context/9001-risk-rating-field/impact.md [--output ...] [--index <dir>]

Assertions supported in case JSON: must_reference, must_not_flag, must_flag, must_contain_label,
must_label_every_claim, banned_phrases, verdict_in, max_hops, impact_json_valid, must_flag_overlap,
story_json_valid, must_keep_edge, must_become_criterion, must_list_overlap, edges_from_seeds_only,
seeds_accounted, design_json_valid, recommends, must_reuse. Every cited `path:line` must exist.

impact_json_valid: the impact.json beside each --output validates as a draft, evidence checked.
must_flag_overlap: each api is the exact backticked Component cell of a row in the table under
`## Overlaps with other stories`. Rows in that table carry no confidence label and are skipped by
must_label_every_claim.

story-refine assertions (story_json_valid, must_keep_edge, must_become_criterion,
must_list_overlap, edges_from_seeds_only, seeds_accounted). A seed is identified by (component,
category, detail). The skill writes scan/edge-seeds.json, so it is not trusted as ground truth:
for must_keep_edge, must_become_criterion, edges_from_seeds_only and seeds_accounted the runner
recomputes tools/index/query.py edge_seeds(load(--index), story.json seeds, <checkout>) and fails
when the saved scan differs from it (parsed JSON compared, order ignored). --index defaults to
<checkout>/index.
story_json_valid: the story.json beside each --output passes validate_story as a draft, evidence
checked, and check_ac has no findings.
must_keep_edge: each name matches an edgeCases row of that story.json whose triple is a seed in
scan/edge-seeds.json: the name equals the row's component, or appears as a whole word in its detail.
must_become_criterion: as must_keep_edge, and the matching edge case has a non-null becameCriterion.
must_list_overlap: as must_flag_overlap, for story.md.
edges_from_seeds_only: every edgeCases triple of that story.json is in the `seeds` list of
scan/edge-seeds.json beside --output (the query.py edge-seeds output the skill saved), with the
seed's evidence and confidence copied unchanged.
seeds_accounted: every seed in scan/edge-seeds.json is an edgeCases or droppedSeeds triple.
For each of them, a missing story.json, edge-seeds.json or index fails.

solution-design assertions (design_json_valid, recommends, must_reuse) read the design.json beside
each --output. When --output is a design.md, must_label_every_claim also reads that design.json:
every component of every option has a row under `## Components` (in its `### OPT-n:` subsection)
whose last cell is the component's confidence label. A missing row or a different label fails, so
the generic row check cannot pass on a table with no rows.
design_json_valid: design.json passes tools/designs/validate_design.py as a draft, evidence checked,
with the index from --index (every non-new component is an index node). The case's indexRoot names
the root the operator builds that index from. A missing index fails.
recommends: "do-nothing" or "change": whether the recommended option is the doNothing one.
must_reuse: the recommended option lists each api with changeType "modify" (delete, review and new are not reuse).
"""
import argparse
import importlib.util
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
sys.path.insert(0, os.path.join(ROOT, "tools", "designs"))
from validate_design import load_index, validate_design  # noqa: E402

_spec = importlib.util.spec_from_file_location("query", os.path.join(ROOT, "tools", "index", "query.py"))
query = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(query)

DEFAULT_INDEX = os.path.join(ROOT, "index")
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


def check_keep_edge(output_path, wanted, index_dir=None, criterion=False):
    """Only edge cases that are real seeds (triple in scan/edge-seeds.json) count.

    With criterion=True (must_become_criterion), a matching edge case also needs a non-null
    becameCriterion."""
    name = "must_become_criterion" if criterion else "must_keep_edge"
    doc, rows, fails = load_seed_rows(output_path, name, index_dir)
    if fails:
        return fails
    known = seed_index(rows)
    ecs = [ec for ec in story_edge_cases(doc) if triple(ec) in known]
    if criterion:
        return [f"no edge case for {w} became a criterion" for w in wanted
                if not any(edge_matches(ec, w) and ec.get("becameCriterion") is not None for ec in ecs)]
    return [f"edge case not kept for {w}" for w in wanted if not any(edge_matches(ec, w) for ec in ecs)]


def recompute_seeds(doc, index_dir):
    """(query.edge_seeds over the story's seeds list, None) or (None, failure text)."""
    seeds = doc.get("seeds") if isinstance(doc, dict) else None
    if not (isinstance(seeds, list) and all(isinstance(s, str) for s in seeds)):
        return None, "story.json has no seeds list to recompute edge seeds from"
    try:
        idx = query.load(index_dir)
        return query.edge_seeds(idx, seeds, ROOT), None
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return None, f"cannot recompute edge seeds from index {index_dir}: {type(exc).__name__}: {exc}"


def canonical_scan(scan):
    """Order-free form of an edge-seeds result: sorted seed JSON and sorted unresolved."""
    if not isinstance(scan, dict):
        return None
    seeds, unresolved = scan.get("seeds"), scan.get("unresolved")
    if not isinstance(seeds, list) or not isinstance(unresolved, list):
        return None
    return (sorted(json.dumps(s, sort_keys=True) for s in seeds),
            sorted(json.dumps(u) for u in unresolved))


def scan_mismatch(saved, fresh):
    """Failure lines when the saved scan differs from the recomputed one; [] when they match."""
    a, b = canonical_scan(saved), canonical_scan(fresh)
    if a is None:
        return ["scan/edge-seeds.json is not {seeds: [...], unresolved: [...]}"]
    if a == b:
        return []
    fails = ["scan/edge-seeds.json differs from query.py edge-seeds recomputed from the index "
             "for the story's seeds"]
    fails += [f"   omitted seed: {s}" for s in sorted(set(b[0]) - set(a[0]))]
    fails += [f"   seed not in the recomputed scan: {s}" for s in sorted(set(a[0]) - set(b[0]))]
    if a[1] != b[1]:
        fails.append(f"   unresolved differs: saved {a[1]}, recomputed {b[1]}")
    return fails


def load_seed_rows(output_path, name, index_dir=None):
    """(story doc, seed rows, []) or (None, None, [failure]).

    The saved scan counts only when it equals edge_seeds() recomputed from the index for the
    story's seeds list, so the skill cannot write its own ground truth."""
    doc, err = load_sibling(output_path, "story.json", name)
    if err:
        return None, None, [err]
    seeds, err = load_sibling(output_path, "scan/edge-seeds.json", name)
    if err:
        return None, None, [err]
    rows = seeds.get("seeds") if isinstance(seeds, dict) else None
    if not isinstance(rows, list):
        return None, None, ["scan/edge-seeds.json has no seeds list"]
    fresh, err = recompute_seeds(doc, index_dir or DEFAULT_INDEX)
    if err:
        return None, None, [err]
    fails = scan_mismatch(seeds, fresh)
    if fails:
        return None, None, fails
    return doc, [s for s in rows if isinstance(s, dict)], []


def check_edges_from_seeds(output_path, index_dir=None):
    doc, rows, fails = load_seed_rows(output_path, "edges_from_seeds_only", index_dir)
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


def check_seeds_accounted(output_path, index_dir=None):
    doc, rows, fails = load_seed_rows(output_path, "seeds_accounted", index_dir)
    if fails:
        return fails
    dropped = doc.get("droppedSeeds") if isinstance(doc, dict) else None
    dropped = [d for d in dropped if isinstance(d, dict)] if isinstance(dropped, list) else []
    seen = {triple(r) for r in story_edge_cases(doc) + dropped}
    return [f"seed {fmt(triple(s))} is neither an edge case nor a dropped seed"
            for s in rows if triple(s) not in seen]


def check_design_json(output_path, index_dir=None):
    """design.json beside --output validates as a draft against the index, evidence checked."""
    doc, err = load_sibling(output_path, "design.json", "design_json_valid")
    if err:
        return [err]
    idx, err = load_index(index_dir or DEFAULT_INDEX)
    if err:
        return [err]
    return [f"design.json invalid: {e}"
            for e in validate_design(doc, "draft", ROOT, idx=idx, check_evidence=True)]


COMPONENTS_HEADING = "## Components"
OPTION_HEADING_RE = re.compile(r"^### (OPT-[0-9]+):")
UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")


def _unescape_cell(text):
    return text.replace("\\|", "|").replace("\\\\", "\\")


def design_component_rows(output_text):
    """{(optionId, api): [last cell, ...]} for the backticked rows under `## Components`."""
    rows, inside, opt = {}, False, None
    for line in output_text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == COMPONENTS_HEADING
            opt = None
            continue
        if not inside:
            continue
        m = OPTION_HEADING_RE.match(line)
        if m:
            opt = m.group(1)
            continue
        if opt and line.startswith("| `"):
            cells = UNESCAPED_PIPE_RE.split(line)[1:-1]
            m = BACKTICKED_RE.match(cells[0].strip()) if cells else None
            if m:
                rows.setdefault((opt, _unescape_cell(m.group(1))), []).append(cells[-1].strip())
    return rows


def check_design_labels(output_path, output_text):
    """design.md beside its design.json: every component of every option has a row under
    `## Components` whose last cell is that component's confidence label. Run under
    must_label_every_claim when --output is a design.md, so the label check cannot pass on a
    table that lost its rows."""
    doc, err = load_sibling(output_path, "design.json", "must_label_every_claim")
    if err:
        return [err]
    rows = design_component_rows(output_text)
    fails = []
    opts = doc.get("options") if isinstance(doc, dict) else None
    for o in opts if isinstance(opts, list) else []:
        comps = o.get("components") if isinstance(o, dict) else None
        for c in comps if isinstance(comps, list) else []:
            if not isinstance(c, dict):
                continue
            key = (o.get("id"), c.get("api"))
            got = rows.get(key)
            if not got:
                fails.append(f"design.md: no Components row for {key[1]} under {key[0]}")
            elif got[0] != c.get("confidence"):
                fails.append(f"design.md: Components row for {key[1]} under {key[0]} is labelled "
                             f"{got[0]!r}; design.json says {c.get('confidence')!r}")
    return fails


def recommended_option(output_path, name):
    """(recommended option dict, None) or (None, failure text)."""
    doc, err = load_sibling(output_path, "design.json", name)
    if err:
        return None, err
    rec = doc.get("recommendation") if isinstance(doc, dict) else None
    opt_id = rec.get("optionId") if isinstance(rec, dict) else None
    opts = doc.get("options") if isinstance(doc, dict) else None
    for o in opts if isinstance(opts, list) else []:
        if isinstance(o, dict) and o.get("id") == opt_id:
            return o, None
    return None, f"{name}: recommendation.optionId {opt_id!r} names no option in design.json"


def check_recommends(output_path, want):
    if want not in ("do-nothing", "change"):
        return [f"recommends: {want!r} is not do-nothing or change"]
    opt, err = recommended_option(output_path, "recommends")
    if err:
        return [err]
    is_dn = opt.get("doNothing") is True
    if is_dn == (want == "do-nothing"):
        return []
    kind = "the do-nothing option" if is_dn else "a change option"
    return [f"recommends: expected {want}, design recommends {opt.get('id')} ({kind})"]


def check_must_reuse(output_path, apis):
    opt, err = recommended_option(output_path, "must_reuse")
    if err:
        return [err]
    comps = opt.get("components") if isinstance(opt.get("components"), list) else []
    reused = {c.get("api") for c in comps if isinstance(c, dict) and c.get("changeType") == "modify"}
    return [f"must_reuse: recommended option {opt.get('id')} does not reuse {api}"
            for api in apis if api not in reused]


def check(output_text, asserts, output_path=None, index_dir=None):
    """index_dir: the index edge seeds are recomputed from (default <checkout>/index)."""
    fails = []
    seed_fails = []

    def add_seed_fails(more):
        # A scan mismatch is reported once, not once per seed-reading assertion.
        for f in more:
            if f not in seed_fails:
                seed_fails.append(f)
                fails.append(f)
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
        if output_path and os.path.basename(output_path) == "design.md":
            fails += check_design_labels(output_path, output_text)
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
        add_seed_fails(check_keep_edge(output_path, asserts["must_keep_edge"], index_dir))
    if asserts.get("must_become_criterion"):
        add_seed_fails(check_keep_edge(output_path, asserts["must_become_criterion"], index_dir,
                                       criterion=True))
    listed = overlap_components(output_text) if asserts.get("must_list_overlap") else set()
    for api in asserts.get("must_list_overlap", []):
        if api not in listed:
            fails.append(f"overlap not listed for {api}")
    if asserts.get("edges_from_seeds_only"):
        add_seed_fails(check_edges_from_seeds(output_path, index_dir))
    if asserts.get("seeds_accounted"):
        add_seed_fails(check_seeds_accounted(output_path, index_dir))
    if asserts.get("design_json_valid"):
        fails += check_design_json(output_path, index_dir)
    if asserts.get("recommends"):
        fails += check_recommends(output_path, asserts["recommends"])
    if asserts.get("must_reuse"):
        fails += check_must_reuse(output_path, asserts["must_reuse"])
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", required=True)
    ap.add_argument("--case", required=True)
    ap.add_argument("--output", action="append", required=True)
    ap.add_argument("--index", default=DEFAULT_INDEX,
                    help="index dir for edge-seed recompute and design checks (default <checkout>/index)")
    a = ap.parse_args()
    case_path = os.path.join(ROOT, "framework", "skills", a.skill, "evals", "cases", a.case + ".json")
    with open(case_path) as fh:
        case = json.load(fh)
    all_ok = True
    for i, out in enumerate(a.output, 1):
        with open(out, encoding="utf-8") as fh:
            txt = fh.read()
        fails = check(txt, case["assert"], out, a.index)
        ok = not fails
        all_ok &= ok
        print(f"run {i}: {'PASS' if ok else 'FAIL'}")
        for f in fails:
            print("   - " + f)
    print(f"\ncase {a.case}: {'PASS' if all_ok else 'FAIL'} over {len(a.output)} run(s)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
