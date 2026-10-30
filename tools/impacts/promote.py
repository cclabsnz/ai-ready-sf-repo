#!/usr/bin/env python3
"""Promote a reviewed draft impact into the register. A human step. stdlib only.

  python3 tools/impacts/promote.py <draft-dir> --confirmed-by "<name or role>" [--replace] [--root .]

Validates <draft-dir>/impact.json as a draft (evidence checked), scans impact.json and impact.md
with the data guard, then writes impacts/<storyId>-<slug>/impact.json (status in-flight, confirmedBy
set) and a byte-for-byte copy of impact.md. Nothing else is copied. The result is validated as
promoted. This script does not decide anything: --confirmed-by records who did.

Exit codes: 0 ok, 1 refused (invalid draft, data hit, destination exists, symlink), 2 bad usage.
Code comes from this checkout (located from __file__); data comes from --root.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

from validate import validate  # noqa: E402

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


def main(argv=None):
    ap = argparse.ArgumentParser(description="Promote a draft impact into impacts/.")
    ap.add_argument("draft_dir")
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
    jsrc = os.path.join(draft, "impact.json")
    msrc = os.path.join(draft, "impact.md")
    for p in (jsrc, msrc):
        if not os.path.isfile(p):
            return refuse("%s is missing" % p)
    try:
        with open(jsrc, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
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
    os.makedirs(dest, exist_ok=True)
    try:
        write_nofollow(djson, (json.dumps(promoted, indent=2, sort_keys=True) + "\n").encode("utf-8"))
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
