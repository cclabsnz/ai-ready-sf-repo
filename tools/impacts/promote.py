#!/usr/bin/env python3
"""Promote a reviewed draft impact into the register. A human step. stdlib only.

  python3 tools/impacts/promote.py <draft-dir> --confirmed-by "<name or role>" [--option OPT-n]
      [--index <dir>] [--replace] [--root .]

Validates <draft-dir>/impact.json as a draft (evidence checked), scans impact.json and impact.md
with the data guard, then writes impacts/<storyId>-<slug>/impact.json (status in-flight, confirmedBy
set) and a byte-for-byte copy of impact.md. Nothing else is copied. The result is validated as
promoted. This script does not decide anything: --confirmed-by records who did.

When <draft-dir> holds design.json (from solution-design), it is validated as a draft against the
index (--index, default <checkout>/index) with evidence checked, and must be for the same storyId
and slug. The chosen option is --option, or the design's recommendation when --option is omitted.
When the impact's designOption is not the chosen option, promotion is refused (exit 1): "impact
assesses OPT-a; re-run story-impact for OPT-b before promoting". The record is re-assessed, never
hand-edited. When the chosen option is the design's doNothing option, an impact with any new,
modify or delete component is refused (exit 1): "the chosen option is do nothing; the impact must
not change components". review components are allowed. Otherwise it also writes design.json (status confirmed, confirmedBy, chosenOption)
and design.md, re-rendered by tools/designs/design_md.py, and adds chosenOption to impact.json.
The design files get the same rules as the impact: no symlinked source, data scan of the draft
and of the final bytes, writes that never follow a symlink, and the same-storyId check (which
looks at impact.json, story.json and design.json in other folders). Without design.json,
--option is a usage error (exit 2), an impact naming a designOption is refused, and a
destination that already holds design.json or design.md is refused; promotion is otherwise as
before.

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
sys.path.insert(2, os.path.join(REPO, "tools", "designs"))

from validate import DO_NOTHING_MSG, OPTION_RE, do_nothing_conflict, validate  # noqa: E402
from validate_story import validate_story  # noqa: E402
from check_ac import check_ac, load_vague  # noqa: E402
from story_md import render_md  # noqa: E402  (tools/stories/story_md.py, shared with write_story.py)
import design_md  # noqa: E402  (tools/designs/design_md.py, shared with write_design.py)
from validate_design import load_index, validate_design  # noqa: E402

SCAN = os.path.join(REPO, "tools", "guard", "scan_data.py")
DEFAULT_INDEX = os.path.join(REPO, "index")
RECORD_FILES = ("impact.json", "story.json", "design.json")


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


def scan_final(json_bytes, md_bytes, *more):
    """Run the data guard on the exact bytes about to be written. Return hit text, or '' if clean.

    more: further (name, bytes) pairs, such as the confirmed design.json and design.md."""
    with tempfile.TemporaryDirectory(prefix="promote_scan_") as tmp:
        paths = []
        for name, data in (("final.json", json_bytes), ("final.md", md_bytes)) + tuple(more):
            p = os.path.join(tmp, name)
            with open(p, "wb") as fh:
                fh.write(data)
            paths.append(p)
        scan = subprocess.run([sys.executable, SCAN] + paths, capture_output=True, text=True)
    return "" if scan.returncode == 0 else (scan.stdout + scan.stderr or "data guard failed\n")


def other_folder_record(imp, dest, story_id):
    """Return the path of an impact.json, story.json or design.json for story_id in a folder
    other than dest."""
    if not os.path.isdir(imp):
        return None
    for name in sorted(os.listdir(imp)):
        folder = os.path.join(imp, name)
        if folder == dest or os.path.islink(folder) or not os.path.isdir(folder):
            continue
        for fname in RECORD_FILES:
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
    ap.add_argument("--option", default=None,
                    help="OPT-<n> the owner chooses from design.json (default: the recommendation)")
    ap.add_argument("--index", default=None,
                    help="index dir for the design component check (default <checkout>/index)")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--root", default=".")
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    who = a.confirmed_by.strip()
    if not who:
        return usage("--confirmed-by must be a non-empty name or role")
    if a.story and (a.option is not None or a.index is not None):
        return usage("--option and --index apply to impact promotion, not --story")
    if a.option is not None and not OPTION_RE.match(a.option):
        return usage("--option '%s' does not match OPT-<n>" % a.option)

    ctx = os.path.join(os.path.realpath(a.root), "ai-context")
    draft = os.path.realpath(a.draft_dir)
    if not draft.startswith(ctx + os.sep):
        return usage("<draft-dir> resolves outside <root>/ai-context/; nothing written")
    if a.story:
        return promote_story(a, who, draft)
    jsrc = os.path.join(draft, "impact.json")
    msrc = os.path.join(draft, "impact.md")
    dsrc = os.path.join(draft, "design.json")
    # lexists, not isfile: a dangling symlink is a design to refuse, never "no design".
    has_design = os.path.lexists(dsrc)
    if a.option is not None and not has_design:
        return usage("--option needs %s; this draft has no design; nothing written" % dsrc)
    for p in (jsrc, msrc) + ((dsrc,) if has_design else ()):
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

    design = chosen = None
    if has_design:
        try:
            with open(dsrc, encoding="utf-8") as fh:
                design = json.load(fh)
        except (OSError, ValueError, RecursionError) as exc:
            return refuse("cannot read design.json: %s" % exc)
        idx, problem = load_index(a.index or DEFAULT_INDEX)
        if problem:
            return usage("%s; nothing written" % problem)
        errors = validate_design(design, "draft", a.root, idx, check_evidence=True)
        if errors:
            for e in errors:
                print(e, file=sys.stderr)
            return refuse("draft design is not valid; nothing written")
        if (design["storyId"], design["slug"]) != (doc["storyId"], doc["slug"]):
            return refuse("design.json is for %s-%s, the impact for %s-%s; nothing written"
                          % (design["storyId"], design["slug"], doc["storyId"], doc["slug"]))
        chosen = a.option or design["recommendation"]["optionId"]
        if chosen not in [o["id"] for o in design["options"]]:
            return refuse("%s is not an option in design.json; nothing written" % chosen)
        if doc.get("designOption") != chosen:
            return refuse("impact assesses %s; re-run story-impact for %s before promoting"
                          % (doc.get("designOption") or "no design option", chosen))
        changed = do_nothing_conflict(doc, design, chosen)
        if changed:
            return refuse("%s (changes: %s); nothing written" % (DO_NOTHING_MSG, ", ".join(changed)))
    elif "designOption" in doc:
        return refuse("impact assesses %s but %s is missing; nothing written"
                      % (doc["designOption"], dsrc))

    scan = subprocess.run([sys.executable, SCAN, jsrc, msrc] + ([dsrc] if has_design else []),
                          capture_output=True, text=True)
    if scan.returncode != 0:
        sys.stderr.write(scan.stdout + scan.stderr)
        return refuse("data guard reported hits; nothing written")

    dest = os.path.join(a.root, "impacts", "%s-%s" % (doc["storyId"], doc["slug"]))
    djson = os.path.join(dest, "impact.json")
    dmd = os.path.join(dest, "impact.md")
    ddjson = os.path.join(dest, "design.json")
    ddmd = os.path.join(dest, "design.md")
    imp = os.path.join(a.root, "impacts")
    for p in (imp, dest, djson, dmd, ddjson, ddmd):
        if os.path.islink(p):
            return refuse("%s is a symlink; nothing written" % p)
    imp_real = os.path.join(os.path.realpath(a.root), "impacts")
    if not os.path.realpath(dest).startswith(imp_real + os.sep):
        return refuse("%s resolves outside <root>/impacts/; nothing written" % dest)
    if os.path.exists(dest) and not a.replace:
        return refuse("%s already exists; use --replace to overwrite" % dest)
    if not has_design:
        for p in (ddjson, ddmd):
            if os.path.lexists(p):
                return refuse("%s is on record but the draft has no design.json; nothing written" % p)
    clash = other_folder_record(imp, dest, doc["storyId"])
    if clash:
        return refuse("story %s already has a record in %s; nothing written" % (doc["storyId"], clash))

    promoted = dict(doc)
    promoted["status"] = "in-flight"
    promoted["confirmedBy"] = who
    if has_design:
        promoted["chosenOption"] = chosen
    errors = validate(promoted, "promoted", a.root)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return refuse("promoted record is not valid; nothing written")
    extra = ()
    if has_design:
        confirmed = dict(design)
        confirmed["status"] = "confirmed"
        confirmed["confirmedBy"] = who
        confirmed["chosenOption"] = chosen
        errors = validate_design(confirmed, "confirmed", a.root, idx)
        if errors:
            for e in errors:
                print(e, file=sys.stderr)
            return refuse("confirmed design is not valid; nothing written")
        extra = (("design.json", (json.dumps(confirmed, indent=2, sort_keys=True) + "\n").encode("utf-8")),
                 ("design.md", design_md.render_md(confirmed).encode("utf-8")))
    with open(msrc, "rb") as fh:
        md_bytes = fh.read()
    json_bytes = (json.dumps(promoted, indent=2, sort_keys=True) + "\n").encode("utf-8")
    hit = scan_final(json_bytes, md_bytes, *extra)
    if hit:
        sys.stderr.write(hit)
        return refuse("data guard reported hits in the final record; nothing written")
    os.makedirs(dest, exist_ok=True)
    try:
        write_nofollow(djson, json_bytes)
        write_nofollow(dmd, md_bytes)
        for name, data in extra:
            write_nofollow(os.path.join(dest, name), data)
    except OSError as exc:
        return refuse("cannot write without following a symlink: %s" % exc)

    with open(djson, encoding="utf-8") as fh:
        errors = validate(json.load(fh), "promoted", a.root)
    if has_design and not errors:
        with open(ddjson, encoding="utf-8") as fh:
            errors = validate_design(json.load(fh), "confirmed", a.root, idx)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return refuse("written record failed promoted validation")
    if has_design:
        print("Chosen option: %s (recommended: %s), confirmed by %s."
              % (chosen, design["recommendation"]["optionId"], who))
    print(dest)
    print("Next: git add %s and open a PR; a reviewer checks the impact before merge." % dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
