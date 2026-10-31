#!/usr/bin/env python3
"""Deterministic story writer for story-refine. stdlib only.

  python3 write_story.py --id DEMO-201 --slug premium-escalation \
      --draft ai-context/DEMO-201-premium-escalation/scan/draft.json [--root .]

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
registerCommit}. story.md is rendered by tools/stories/story_md.py, the renderer promote.py
--story also uses for the confirmed record.

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
from story_md import cell, render_md  # noqa: E402,F401  (tools/stories/story_md.py; promote.py uses it too)

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
