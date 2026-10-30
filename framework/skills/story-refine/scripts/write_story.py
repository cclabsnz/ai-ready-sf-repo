#!/usr/bin/env python3
"""Deterministic story writer for story-refine. stdlib only.

  python3 write_story.py --id DEMO-201 --slug premium-escalation-refined \
      --draft ai-context/DEMO-201-premium-escalation-refined/scan/draft.json [--root .]

draft.json is the story record without schemaVersion, status, overlaps and confirmedBy; the
writer fills those in. A draft that carries any of them, or a storyId or slug that differs
from --id or --slug, is refused. overlaps are computed from the draft's seeds: each seed goes
through tools/impacts/register.py overlaps() as a changeType "review" component, so every
overlap at refinement is a watch.

The record is validated as a draft (tools/stories/validate_story.py, evidence checked against
--root) and its acceptance criteria are checked (tools/stories/check_ac.py) before anything is
written. On any error the errors go to stderr, nothing is written and the exit code is 1. Exit 2
is bad usage, including an output folder that resolves (realpath) outside <root>/ai-context/ or
outside this checkout's ai-context/ (located from __file__). On success it writes
ai-context/<id>-<slug>/story.json and story.md and prints {storyJson, storyMd, overlaps,
registerCommit}.

Code comes from this checkout (located from __file__); data comes from --root.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# scripts -> story-refine -> skills -> framework|.claude|.github -> repo root
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
sys.path.insert(0, os.path.join(REPO, "tools", "stories"))
sys.path.insert(0, os.path.join(REPO, "tools", "impacts"))

from validate import STORY_RE, SLUG_RE  # noqa: E402
from register import load_register, overlaps, register_commit  # noqa: E402
from safe_write import checkout_out_dir, write_nofollow  # noqa: E402
from validate_story import validate_story  # noqa: E402
from check_ac import check_ac, load_vague  # noqa: E402

FILLED = ("schemaVersion", "status", "overlaps", "confirmedBy")


def seed_types(root):
    """api -> metadata type from <root>/index/metadata.json; {} when the index is unreadable."""
    try:
        with open(os.path.join(root, "index", "metadata.json"), encoding="utf-8") as fh:
            nodes = json.load(fh).get("nodes", {})
    except (OSError, ValueError, AttributeError):
        return {}
    if not isinstance(nodes, dict):
        return {}
    return {k: v.get("type") for k, v in nodes.items() if isinstance(v, dict)}


def seed_overlaps(story, seeds, root, impacts):
    """register.overlaps() for the seeds, each as a changeType "review" component."""
    if not isinstance(seeds, list):
        return []
    types = seed_types(root)
    comps = []
    for s in dict.fromkeys(x for x in seeds if isinstance(x, str) and x.strip()):
        t = types.get(s)
        comps.append({"api": s, "type": t if isinstance(t, str) and t.strip() else "Unknown",
                      "changeType": "review"})
    return overlaps({"storyId": story, "components": comps}, impacts)


def cell(v):
    """One markdown table cell: backslashes escaped first, then pipes; newlines become spaces."""
    return "" if v is None else str(v).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def overlap_lines(found, invalid, reg_commit):
    """The impact.md Overlaps section, same table shape (write_report.py)."""
    lines = ["", "## Overlaps with other stories", ""]
    if found:
        lines += ["| Component | Kind | Other story | Squad | Status | Their change | Register commit |",
                  "|---|---|---|---|---|---|---|"]
        for o in found:
            for s in o["stories"]:
                lines.append("| `%s` | %s | %s | %s | %s | %s | `%s` |" % (
                    o["api"], o["kind"], cell(s.get("storyId")), cell(s.get("squad")),
                    cell(s.get("status")), cell(s.get("changeType")), cell(s.get("commit"))))
    else:
        lines.append("- none in the register at `%s`" % reg_commit)
    if invalid:
        lines += ["", "### Register files that failed validation", ""]
        for item in invalid:
            lines.append("- `%s`: %s" % (item["path"], "; ".join(cell(e) for e in item["errors"])))
    return lines


def bullets(items):
    return ["- %s" % cell(i) for i in items] or ["- none"]


def render_md(doc, invalid, reg_commit):
    seeds = ", ".join("`%s`" % cell(s) for s in doc["seeds"]) or "none"
    lines = ["# Story: %s %s" % (doc["storyId"], doc["slug"]), "",
             "Status: %s. Squad: %s. Seeds: %s." % (doc["status"], cell(doc["squad"]), seeds), "",
             "- Persona: %s" % cell(doc["persona"]),
             "- Goal: %s" % cell(doc["goal"]),
             "- Benefit: %s" % cell(doc["benefit"])]
    lines += ["", "## Acceptance criteria", ""]
    if doc["acceptanceCriteria"]:
        lines += ["| AC | Given | When | Then | Examples | Source |", "|---|---|---|---|---|---|"]
        for a in doc["acceptanceCriteria"]:
            lines.append("| %s | %s | %s | %s | %s | %s |" % (
                cell(a["id"]), cell(a["given"]), cell(a["when"]), cell(a["then"]),
                cell("; ".join(a["examples"])), cell(a["source"])))
    else:
        lines.append("- none")
    lines += ["", "## Edge cases", ""]
    if doc["edgeCases"]:
        lines += ["| EC | Category | Component | Detail | Evidence | Confidence | Criterion |",
                  "|---|---|---|---|---|---|---|"]
        for c in doc["edgeCases"]:
            ev = "`%s`" % cell(c["evidence"]) if c["evidence"] is not None else "none"
            crit = cell(c["becameCriterion"]) if c["becameCriterion"] is not None else \
                "none: %s" % cell(c["reason"])
            lines.append("| %s | %s | `%s` | %s | %s | %s | %s |" % (
                cell(c["id"]), cell(c["category"]), cell(c["component"]), cell(c["detail"]), ev,
                cell(c["confidence"]), crit))
    else:
        lines.append("- none")
    lines += ["", "## Dropped seeds", ""]
    if doc["droppedSeeds"]:
        lines += ["| Category | Component | Detail | Reason |", "|---|---|---|---|"]
        for d in doc["droppedSeeds"]:
            lines.append("| %s | `%s` | %s | %s |" % (cell(d["category"]), cell(d["component"]),
                                                     cell(d["detail"]), cell(d["reason"])))
    else:
        lines.append("- none")
    lines += overlap_lines(doc["overlaps"], invalid, reg_commit)
    lines += ["", "## Open questions", ""]
    if doc["openQuestions"]:
        lines += ["| OQ | Question | Owner role | Answer | Deferred |", "|---|---|---|---|---|"]
        for q in doc["openQuestions"]:
            lines.append("| %s | %s | %s | %s | %s |" % (
                cell(q["id"]), cell(q["text"]), cell(q["ownerRole"]),
                cell(q["answer"]) if q["answer"] is not None else "none",
                "yes" if q["deferred"] else "no"))
    else:
        lines.append("- none")
    lines += ["", "## Scope", "", "### In scope", ""] + bullets(doc["inScope"])
    lines += ["", "### Out of scope", ""] + bullets(doc["outOfScope"])
    lines += ["", "### Non-functional", ""] + bullets(doc["nonFunctional"])
    lines += ["", "_Generated by write_story.py from story.json (status draft). The product owner "
                  "confirms a story by promoting it; the assistant never confirms one. The Overlaps "
                  "section comes from the register and is reported as written; at refinement every "
                  "overlap is a watch._"]
    return "\n".join(lines) + "\n"


def usage(msg):
    print(msg, file=sys.stderr)
    return 2


def fail(errors):
    for e in errors:
        print(e, file=sys.stderr)
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write story.json and story.md for one story.")
    ap.add_argument("--id", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--draft", required=True)
    ap.add_argument("--root", default=".")
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if not STORY_RE.match(a.id):
        return usage("--id '%s' does not match %s" % (a.id, STORY_RE.pattern))
    if not SLUG_RE.match(a.slug):
        return usage("--slug '%s' does not match %s" % (a.slug, SLUG_RE.pattern))
    try:
        out_dir = checkout_out_dir(a.root, "%s-%s" % (a.id, a.slug))
    except ValueError:
        return usage("output folder for %s-%s resolves outside <root>/ai-context/ or outside the "
                     "checkout's ai-context/; nothing written" % (a.id, a.slug))
    try:
        with open(a.draft, encoding="utf-8") as fh:
            draft = json.load(fh)
    except (OSError, ValueError) as exc:
        return usage("cannot read draft JSON: %s" % exc)
    if not isinstance(draft, dict):
        return usage("--draft is not a JSON object")

    errors = ["draft carries '%s'; write_story.py fills it in" % k for k in FILLED if k in draft]
    for key, want in (("storyId", a.id), ("slug", a.slug)):
        if key in draft and draft[key] != want:
            errors.append("draft %s '%s' differs from --%s '%s'"
                          % (key, draft[key], "id" if key == "storyId" else key, want))
    if errors:
        return fail(errors)

    reg = load_register(a.root)
    doc = dict(draft)
    doc.update({"schemaVersion": 1, "storyId": a.id, "slug": a.slug, "status": "draft",
                "overlaps": seed_overlaps(a.id, draft.get("seeds"), a.root, reg["impacts"])})
    errors = validate_story(doc, "draft", a.root, check_evidence=True)
    if errors:
        return fail(errors)
    findings = check_ac(doc, load_vague())
    if findings:
        return fail(["%s: %s: %s" % (f["id"], f["rule"], f["detail"]) for f in findings])

    reg_commit = register_commit(a.root)
    md = render_md(doc, reg["invalid"], reg_commit)

    jpath = os.path.join(out_dir, "story.json")
    mpath = os.path.join(out_dir, "story.md")
    for p in (jpath, mpath):
        if os.path.islink(p):
            return usage("%s is a symlink; nothing written" % p)
    os.makedirs(out_dir, exist_ok=True)
    try:
        write_nofollow(jpath, (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        write_nofollow(mpath, md.encode("utf-8"))
    except OSError as exc:
        return usage("cannot write output without following a symlink: %s" % exc)
    print(json.dumps({"storyJson": jpath, "storyMd": mpath, "overlaps": len(doc["overlaps"]),
                      "registerCommit": reg_commit}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
