#!/usr/bin/env python3
"""Promote a reviewed draft impact into the register. A human step. stdlib only.

  python3 tools/impacts/promote.py <draft-dir> --confirmed-by "<name or role>" [--replace] [--root .]

Validates <draft-dir>/impact.json as a draft (evidence checked), scans impact.json and impact.md
with the data guard, then writes impacts/<storyId>-<slug>/impact.json (status in-flight, confirmedBy
set) and a byte-for-byte copy of impact.md. Nothing else is copied. The result is validated as
promoted. This script does not decide anything: --confirmed-by records who did.

With --story, promotes <draft-dir>/story.json instead, to impacts/<storyId>-<slug>/story.json
(status confirmed, confirmedBy set). story.md is not copied: it is re-rendered from the confirmed
record by tools/stories/story_md.py (the writer's renderer), so it states the confirmed status,
the confirmer and every answer and deferral; overlaps are shown as recorded at refinement.
Refusal order: draft validation with evidence, acceptance criteria check, open questions, data
scan of the draft, destination checks, data scan of the final bytes. Before writing, it prints
every deferred question (id, owner role, deferred by, text) and every answered one with its
answer. impact.json and impact.md are never touched. --replace applies only to story.json and
story.md.

Exit codes: 0 ok, 1 refused (invalid draft, data hit, destination exists, symlink), 2 bad usage.
Code comes from this checkout (located from __file__); data comes from --root.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(REPO, "tools", "stories"))

from validate import validate  # noqa: E402
from validate_story import validate_story  # noqa: E402
from check_ac import check_ac, load_vague  # noqa: E402
from story_md import render_md  # noqa: E402  (tools/stories/story_md.py, shared with write_story.py)

SCAN = os.path.join(REPO, "tools", "guard", "scan_data.py")


def usage(msg):
    print(msg, file=sys.stderr)
    return 2


def refuse(msg):
    print(msg, file=sys.stderr)
    return 1


def write_nofollow(path, data):
    """Write bytes to path, never through a symlink."""
    if os.path.islink(path):
        raise OSError("%s is a symlink" % path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o644)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def scan_final(json_bytes, md_bytes):
    """Run the data guard on the exact bytes about to be written. Return hit text, or '' if clean."""
    with tempfile.TemporaryDirectory(prefix="promote_scan_") as tmp:
        paths = []
        for name, data in (("final.json", json_bytes), ("final.md", md_bytes)):
            p = os.path.join(tmp, name)
            with open(p, "wb") as fh:
                fh.write(data)
            paths.append(p)
        scan = subprocess.run([sys.executable, SCAN] + paths, capture_output=True, text=True)
    return "" if scan.returncode == 0 else (scan.stdout + scan.stderr or "data guard failed\n")


def other_folder_record(imp, dest, story_id):
    """Return the path of an impact.json or story.json for story_id in a folder other than dest."""
    if not os.path.isdir(imp):
        return None
    for name in sorted(os.listdir(imp)):
        folder = os.path.join(imp, name)
        if folder == dest or os.path.islink(folder) or not os.path.isdir(folder):
            continue
        for fname in ("impact.json", "story.json"):
            other = os.path.join(folder, fname)
            if os.path.islink(other) or not os.path.isfile(other):
                continue
            try:
                with open(other, encoding="utf-8") as fh:
                    rec = json.load(fh)
            except (OSError, ValueError, RecursionError):
                continue
            if isinstance(rec, dict) and rec.get("storyId") == story_id:
                return other
    return None


def confirmation_summary(doc):
    """Lines listing what the confirmer confirms past: deferred questions, then answered ones."""
    def one_line(v):
        return " ".join(str(v).split())

    qs = doc["openQuestions"]
    deferred = [q for q in qs if q["deferred"] is True]
    answered = [q for q in qs if isinstance(q["answer"], str) and q["answer"].strip()]
    lines = ["Open questions at confirmation (story %s):" % doc["storyId"], "Deferred:"]
    lines += ["- %s (owner role: %s; deferred by: %s): %s" % (
        q["id"], one_line(q["ownerRole"]), one_line(q["deferredBy"]), one_line(q["text"]))
        for q in deferred] or ["- none"]
    lines.append("Answered:")
    lines += ["- %s (owner role: %s): %s -> answer: %s" % (
        q["id"], one_line(q["ownerRole"]), one_line(q["text"]), one_line(q["answer"]))
        for q in answered] or ["- none"]
    return lines


def promote_story(a, who, draft):
    """Promote a refined story.json and story.md; never touches impact.json or impact.md."""
    jsrc = os.path.join(draft, "story.json")
    msrc = os.path.join(draft, "story.md")
    for p in (jsrc, msrc):
        if os.path.islink(p):
            return refuse("%s is a symlink; nothing written" % p)
        if not os.path.isfile(p):
            return refuse("%s is missing" % p)
    try:
        with open(jsrc, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError, RecursionError) as exc:
        return refuse("cannot read story.json: %s" % exc)
    errors = validate_story(doc, "draft", a.root, check_evidence=True)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return refuse("draft story is not valid; nothing written")

    findings = check_ac(doc, load_vague())
    if findings:
        for f in findings:
            print("%s %s: %s" % (f["id"], f["rule"], f["detail"]), file=sys.stderr)
        return refuse("acceptance criteria have findings; nothing written")

    open_qs = [q["id"] for q in doc["openQuestions"]
               if not (isinstance(q["answer"], str) and q["answer"].strip()) and q["deferred"] is not True]
    if open_qs:
        return refuse("open questions neither answered nor deferred: %s; nothing written" % ", ".join(open_qs))

    scan = subprocess.run([sys.executable, SCAN, jsrc, msrc], capture_output=True, text=True)
    if scan.returncode != 0:
        sys.stderr.write(scan.stdout + scan.stderr)
        return refuse("data guard reported hits; nothing written")

    # storyId and slug are validated above, so the path below is built from safe values.
    imp = os.path.join(a.root, "impacts")
    dest = os.path.join(imp, "%s-%s" % (doc["storyId"], doc["slug"]))
    djson = os.path.join(dest, "story.json")
    dmd = os.path.join(dest, "story.md")
    for p in (imp, dest, djson, dmd):
        if os.path.islink(p):
            return refuse("%s is a symlink; nothing written" % p)
    imp_real = os.path.join(os.path.realpath(a.root), "impacts")
    if not os.path.realpath(dest).startswith(imp_real + os.sep):
        return refuse("%s resolves outside <root>/impacts/; nothing written" % dest)
    if not a.replace:
        for p in (djson, dmd):
            if os.path.exists(p):
                return refuse("%s already exists; use --replace to overwrite" % p)
    clash = other_folder_record(imp, dest, doc["storyId"])
    if clash:
        return refuse("story %s already has a record in %s; nothing written" % (doc["storyId"], clash))

    confirmed = dict(doc)
    confirmed["status"] = "confirmed"
    confirmed["confirmedBy"] = who
    errors = validate_story(confirmed, "confirmed", a.root)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return refuse("confirmed record is not valid; nothing written")
    # Overlaps were computed at refinement: no register re-read, no promotion-time commit.
    md_bytes = render_md(confirmed, [], None).encode("utf-8")
    json_bytes = (json.dumps(confirmed, indent=2, sort_keys=True) + "\n").encode("utf-8")
    hit = scan_final(json_bytes, md_bytes)
    if hit:
        sys.stderr.write(hit)
        return refuse("data guard reported hits in the final record; nothing written")
    print("\n".join(confirmation_summary(confirmed)))
    os.makedirs(dest, exist_ok=True)
    try:
        write_nofollow(djson, json_bytes)
        write_nofollow(dmd, md_bytes)
    except OSError as exc:
        return refuse("cannot write without following a symlink: %s" % exc)

    with open(djson, encoding="utf-8") as fh:
        errors = validate_story(json.load(fh), "confirmed", a.root)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return refuse("written record failed confirmed validation")
    print(dest)
    print("Next: git add %s and open a PR; a reviewer checks the story before merge." % dest)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Promote a draft impact into impacts/.")
    ap.add_argument("draft_dir")
    ap.add_argument("--story", action="store_true",
                    help="promote story.json and story.md instead of impact.json and impact.md")
    ap.add_argument("--confirmed-by", required=True)
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--root", default=".")
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    who = a.confirmed_by.strip()
    if not who:
        return usage("--confirmed-by must be a non-empty name or role")

    ctx = os.path.join(os.path.realpath(a.root), "ai-context")
    draft = os.path.realpath(a.draft_dir)
    if not draft.startswith(ctx + os.sep):
        return usage("<draft-dir> resolves outside <root>/ai-context/; nothing written")
    if a.story:
        return promote_story(a, who, draft)
    jsrc = os.path.join(draft, "impact.json")
    msrc = os.path.join(draft, "impact.md")
    for p in (jsrc, msrc):
        if os.path.islink(p):
            return refuse("%s is a symlink; nothing written" % p)
        if not os.path.isfile(p):
            return refuse("%s is missing" % p)
    try:
        with open(jsrc, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError, RecursionError) as exc:
        return refuse("cannot read impact.json: %s" % exc)
    errors = validate(doc, "draft", a.root, check_evidence=True)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return refuse("draft is not valid; nothing written")

    scan = subprocess.run([sys.executable, SCAN, jsrc, msrc], capture_output=True, text=True)
    if scan.returncode != 0:
        sys.stderr.write(scan.stdout + scan.stderr)
        return refuse("data guard reported hits; nothing written")

    dest = os.path.join(a.root, "impacts", "%s-%s" % (doc["storyId"], doc["slug"]))
    djson = os.path.join(dest, "impact.json")
    dmd = os.path.join(dest, "impact.md")
    imp = os.path.join(a.root, "impacts")
    for p in (imp, dest, djson, dmd):
        if os.path.islink(p):
            return refuse("%s is a symlink; nothing written" % p)
    imp_real = os.path.join(os.path.realpath(a.root), "impacts")
    if not os.path.realpath(dest).startswith(imp_real + os.sep):
        return refuse("%s resolves outside <root>/impacts/; nothing written" % dest)
    if os.path.exists(dest) and not a.replace:
        return refuse("%s already exists; use --replace to overwrite" % dest)
    clash = other_folder_record(imp, dest, doc["storyId"])
    if clash:
        return refuse("story %s already has a record in %s; nothing written" % (doc["storyId"], clash))

    promoted = dict(doc)
    promoted["status"] = "in-flight"
    promoted["confirmedBy"] = who
    errors = validate(promoted, "promoted", a.root)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return refuse("promoted record is not valid; nothing written")
    with open(msrc, "rb") as fh:
        md_bytes = fh.read()
    json_bytes = (json.dumps(promoted, indent=2, sort_keys=True) + "\n").encode("utf-8")
    hit = scan_final(json_bytes, md_bytes)
    if hit:
        sys.stderr.write(hit)
        return refuse("data guard reported hits in the final record; nothing written")
    os.makedirs(dest, exist_ok=True)
    try:
        write_nofollow(djson, json_bytes)
        write_nofollow(dmd, md_bytes)
    except OSError as exc:
        return refuse("cannot write without following a symlink: %s" % exc)

    with open(djson, encoding="utf-8") as fh:
        errors = validate(json.load(fh), "promoted", a.root)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return refuse("written record failed promoted validation")
    print(dest)
    print("Next: git add %s and open a PR; a reviewer checks the impact before merge." % dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
