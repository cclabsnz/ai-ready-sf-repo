#!/usr/bin/env python3
"""Deterministic design writer for solution-design. stdlib only.

  python3 write_design.py --id DEMO-202 --slug round-robin-assignment \
      --draft ai-context/DEMO-202-round-robin-assignment/scan/design-draft.json \
      [--index index] [--source-root <dir>] [--root .] [--model <name>] [--assistant-version <version>]

draft.json is the design record without schemaVersion, status, provenance, confirmedBy and
chosenOption; the writer fills in the first three, and the last two are added only at promotion.
A draft that carries any of them, or a storyId or slug that differs from --id or --slug, is refused.

provenance: indexStamp is the loaded index's stamp, frameworkVersion is <root>/VERSION (as
write_report.py reads it), model and assistantVersion come from --model and
--assistant-version (default "unknown"), and sourceRoot is the source root the design was written
for, relative to --root with forward slashes ("." for the root itself). --source-root defaults to
the configured source root: tools/config/framework_config.py (this checkout's code) reading
<root>/.ai-framework.json. Either way it must be a relative path that resolves (realpath) to a
folder inside --root; otherwise, or when the config is invalid, it is exit 2 and nothing is
written. The writer does not check that --index was built from that source root; pass the index
of the same root (for greenfield, build_index.py --root demo/greenfield).

--index (default <checkout>/index, located from __file__) is loaded with tools/index/query.py
load(). A missing or unreadable index is exit 2. The record is validated as a draft by
tools/designs/validate_design.py with that index (every non-new component is an index node) and
with evidence checked against --root, before anything is written. On any error the errors go to
stderr, nothing is written and the exit code is 1. Exit 2 is bad usage, including an output folder
that resolves (realpath) outside <root>/ai-context/ or outside this checkout's ai-context/, or an
output file that is a symlink. On success it writes ai-context/<id>-<slug>/design.json and design.md
and prints {designJson, designMd, recommendedOption, indexCommit}. design.md is rendered by
tools/designs/design_md.py, the renderer promotion also uses for the confirmed record.

The output states facts: the options, their trade-offs and components, and which option the
assistant recommended with the reasons given. A named owner confirms an option at promotion.

Code comes from this checkout (located from __file__); data comes from --root.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# scripts -> solution-design -> skills -> framework|.claude|.github -> repo root
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
sys.path.insert(0, os.path.join(REPO, "tools", "designs"))
sys.path.insert(0, os.path.join(REPO, "tools", "impacts"))
sys.path.insert(0, os.path.join(REPO, "tools", "config"))

import framework_config  # noqa: E402  (tools/config/framework_config.py, the one config reader)
from validate import STORY_RE, SLUG_RE  # noqa: E402
from safe_write import checkout_out_dir, write_nofollow  # noqa: E402
from validate_design import load_index, source_root_problem, validate_design  # noqa: E402
from design_md import render_md  # noqa: E402  (tools/designs/design_md.py; promotion uses it too)

DEFAULT_INDEX = os.path.join(REPO, "index")
FILLED = ("schemaVersion", "status", "provenance", "confirmedBy", "chosenOption")


def framework_version(root):
    try:
        with open(os.path.join(root, "VERSION"), encoding="utf-8") as fh:
            v = fh.read().strip()
        return v or "unknown"
    except OSError:
        return "unknown"


def index_stamp(idx):
    st = idx.get("stamp")
    if isinstance(st, dict) and isinstance(st.get("commit"), str) and st["commit"].strip():
        return st
    return {"commit": "unknown", "error": "index stamp has no commit"}


def _inside(top, path):
    """True when path is top or below it. On Windows, paths on different drives are never inside."""
    try:
        return os.path.commonpath([top, path]) == top
    except ValueError:
        return False


def resolve_source_root(root, given):
    """(repo-relative path with forward slashes, None) or (None, problem text).

    given None means the configured sourceRoot (framework_config.source_root, which also checks
    it is a folder inside root)."""
    top = os.path.realpath(root)
    if given is None:
        try:
            path = framework_config.source_root(root)
        except ValueError as exc:
            return None, str(exc)
    else:
        if not given.strip() or os.path.isabs(given) or given.startswith(("/", "\\")):
            return None, "--source-root '%s' is not a path relative to --root" % given
        path = os.path.realpath(os.path.join(top, given))
        if not _inside(top, path):
            return None, "--source-root '%s' resolves outside --root" % given
        if not os.path.isdir(path):
            return None, "--source-root '%s' is not a directory under --root" % given
    rel = os.path.relpath(path, top).replace(os.sep, "/")
    problem = source_root_problem(rel)
    if problem:
        return None, "source root '%s' %s" % (rel, problem)
    return rel, None


def usage(msg):
    print(msg, file=sys.stderr)
    return 2


def fail(errors):
    for e in errors:
        print(e, file=sys.stderr)
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write design.json and design.md for one story.")
    ap.add_argument("--id", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--draft", required=True)
    ap.add_argument("--index", default=DEFAULT_INDEX)
    ap.add_argument("--source-root", default=None,
                    help="source root relative to --root (default: sourceRoot in .ai-framework.json)")
    ap.add_argument("--root", default=".")
    ap.add_argument("--model", default="unknown")
    ap.add_argument("--assistant-version", default="unknown")
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
    source_root, err = resolve_source_root(a.root, a.source_root)
    if err:
        return usage("%s; nothing written" % err)
    idx, err = load_index(a.index)
    if err:
        return usage("%s; build it with python3 tools/index/build_index.py; nothing written" % err)
    try:
        with open(a.draft, encoding="utf-8") as fh:
            draft = json.load(fh)
    except (OSError, ValueError) as exc:
        return usage("cannot read draft JSON: %s" % exc)
    if not isinstance(draft, dict):
        return usage("--draft is not a JSON object")

    errors = ["draft carries '%s'; write_design.py fills it in or promotion adds it" % k
              for k in FILLED if k in draft]
    for key, want in (("storyId", a.id), ("slug", a.slug)):
        if key in draft and draft[key] != want:
            errors.append("draft %s '%s' differs from --%s '%s'"
                          % (key, draft[key], "id" if key == "storyId" else key, want))
    if errors:
        return fail(errors)

    doc = dict(draft)
    doc.update({"schemaVersion": 1, "storyId": a.id, "slug": a.slug, "status": "draft",
                "provenance": {"indexStamp": index_stamp(idx),
                               "frameworkVersion": framework_version(a.root),
                               "model": a.model, "assistantVersion": a.assistant_version,
                               "sourceRoot": source_root}})
    errors = validate_design(doc, "draft", a.root, idx=idx, check_evidence=True)
    if errors:
        return fail(errors)
    # Both outputs are rendered to bytes before either is written.
    jbytes = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")
    mbytes = render_md(doc).encode("utf-8")

    jpath = os.path.join(out_dir, "design.json")
    mpath = os.path.join(out_dir, "design.md")
    for p in (jpath, mpath):
        if os.path.islink(p):
            return usage("%s is a symlink; nothing written" % p)
    os.makedirs(out_dir, exist_ok=True)
    try:
        write_nofollow(jpath, jbytes)
    except OSError as exc:
        return usage("cannot write output without following a symlink: %s" % exc)
    try:
        write_nofollow(mpath, mbytes)
    except OSError as exc:
        # design.json without its design.md is a half-written result: remove it.
        try:
            os.remove(jpath)
        except OSError:
            pass
        return usage("cannot write %s (%s); design.json removed, nothing written" % (mpath, exc))
    print(json.dumps({"designJson": jpath, "designMd": mpath,
                      "recommendedOption": doc["recommendation"]["optionId"],
                      "indexCommit": doc["provenance"]["indexStamp"]["commit"],
                      "sourceRoot": source_root}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
